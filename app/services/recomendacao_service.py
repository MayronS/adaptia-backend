"""
Combina duas estratégias:

1. Score de dificuldade real (60%)
   Baseado na taxa de erro do aluno em cada tópico.
   Tópicos onde o aluno mais erra recebem score mais alto.
   Tópicos nunca tentados recebem score médio (0.5) para incentivar exploração.

2. Filtragem colaborativa (40%)
   Calcula similaridade de cosseno entre o vetor de pontuações do aluno
   e os vetores dos demais alunos. Tópicos que alunos similares concluíram
   (e que o aluno atual ainda não fez) recebem bônus de score.

Score final = 0.6 × score_dificuldade + 0.4 × score_colaborativo
"""

import uuid
import numpy as np
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sklearn.metrics.pairwise import cosine_similarity

from app.models.models import (
    Topico, ProgressoTopico, TentativaQuiz, Quiz,
    Recomendacao, StatusProgresso,
)

PESO_DIFICULDADE  = 0.6
PESO_COLABORATIVO = 0.4
MIN_SCORE         = 0.05
TOP_N             = 5
SCORE_SEM_DADOS   = 0.5   # score para tópicos nunca tentados


async def gerar_recomendacoes(usuario_id: uuid.UUID, db: AsyncSession) -> list[Recomendacao]:
    """Gera (ou atualiza) as recomendações para um aluno."""

    # ── 1. Tópicos disponíveis/em_progresso para o aluno ──────────────────────
    res = await db.execute(
        select(ProgressoTopico).where(
            ProgressoTopico.usuario_id == usuario_id,
            ProgressoTopico.status.in_([StatusProgresso.disponivel, StatusProgresso.em_progresso])
        )
    )
    progressos_aluno = res.scalars().all()

    if not progressos_aluno:
        return []

    topico_ids_candidatos = [p.topico_id for p in progressos_aluno]

    # ── 2. Busca tópicos e quizzes dos candidatos ──────────────────────────────
    res = await db.execute(select(Topico).where(Topico.id.in_(topico_ids_candidatos)))
    topicos = {t.id: t for t in res.scalars().all()}

    # Mapa topico_id → quiz_ids
    res = await db.execute(select(Quiz).where(Quiz.topico_id.in_(topico_ids_candidatos)))
    quizzes_por_topico: dict[uuid.UUID, list[uuid.UUID]] = {}
    for q in res.scalars().all():
        quizzes_por_topico.setdefault(q.topico_id, []).append(q.id)

    # ── 3. Tentativas do aluno nesses tópicos ──────────────────────────────────
    todos_quiz_ids = [qid for qids in quizzes_por_topico.values() for qid in qids]

    acertos_por_topico: dict[uuid.UUID, int] = {}
    total_por_topico:   dict[uuid.UUID, int] = {}

    if todos_quiz_ids:
        res = await db.execute(
            select(TentativaQuiz).where(
                TentativaQuiz.usuario_id == usuario_id,
                TentativaQuiz.quiz_id.in_(todos_quiz_ids),
            )
        )
        for tent in res.scalars().all():
            # Descobre topico_id pelo quiz
            for tid, qids in quizzes_por_topico.items():
                if tent.quiz_id in qids:
                    acertos_por_topico[tid] = acertos_por_topico.get(tid, 0) + tent.acertos
                    total_por_topico[tid]   = total_por_topico.get(tid, 0) + tent.total_questoes
                    break

    # ── 4. Score de dificuldade real ───────────────────────────────────────────
    # Taxa de erro = 1 - (acertos / total)
    # Tópico nunca tentado = score médio (incentiva exploração)
    scores_dificuldade: dict[uuid.UUID, float] = {}
    for tid in topico_ids_candidatos:
        total = total_por_topico.get(tid, 0)
        if total == 0:
            scores_dificuldade[tid] = SCORE_SEM_DADOS
        else:
            taxa_acerto = acertos_por_topico.get(tid, 0) / total
            scores_dificuldade[tid] = round(1.0 - taxa_acerto, 4)  # erro alto = score alto

    # ── 5. Score colaborativo ──────────────────────────────────────────────────
    scores_colab: dict[uuid.UUID, float] = {tid: 0.0 for tid in topico_ids_candidatos}

    res = await db.execute(
        select(ProgressoTopico).where(ProgressoTopico.topico_id.in_(topico_ids_candidatos))
    )
    todos_progressos = res.scalars().all()

    usuarios_ids = list({p.usuario_id for p in todos_progressos})
    topicos_ids  = topico_ids_candidatos

    if len(usuarios_ids) > 1:
        u_idx = {u: i for i, u in enumerate(usuarios_ids)}
        t_idx = {t: i for i, t in enumerate(topicos_ids)}

        matriz = np.zeros((len(usuarios_ids), len(topicos_ids)))
        for p in todos_progressos:
            matriz[u_idx[p.usuario_id], t_idx[p.topico_id]] = p.pontuacao

        if usuario_id in u_idx:
            idx_aluno   = u_idx[usuario_id]
            vetor_aluno = matriz[idx_aluno].reshape(1, -1)
            sims        = cosine_similarity(vetor_aluno, matriz)[0]

            for i, sim in enumerate(sims):
                if usuarios_ids[i] == usuario_id or sim < 0.1:
                    continue
                for p in todos_progressos:
                    if (p.usuario_id == usuarios_ids[i]
                            and p.status == StatusProgresso.concluido
                            and p.topico_id in t_idx):
                        scores_colab[p.topico_id] = max(scores_colab[p.topico_id], sim)

    # ── 6. Score final e motivo ────────────────────────────────────────────────
    resultados: list[tuple[uuid.UUID, float, str]] = []
    for tid in topico_ids_candidatos:
        sd     = scores_dificuldade.get(tid, SCORE_SEM_DADOS)
        sc     = scores_colab.get(tid, 0.0)
        score_final = PESO_DIFICULDADE * sd + PESO_COLABORATIVO * sc

        if score_final < MIN_SCORE:
            continue

        total = total_por_topico.get(tid, 0)
        if total == 0:
            motivo = "tópico ainda não praticado"
        elif sd >= 0.7:
            motivo = "dificuldade alta detectada"
        elif sd >= 0.4:
            motivo = "dificuldade moderada detectada"
        elif sc > sd:
            motivo = "alunos similares avançaram aqui"
        else:
            motivo = "sequência natural de aprendizado"

        resultados.append((tid, round(score_final, 4), motivo))

    resultados.sort(key=lambda x: x[1], reverse=True)
    resultados = resultados[:TOP_N]

    # ── 7. Persiste recomendações (upsert) ─────────────────────────────────────
    novas: list[Recomendacao] = []
    for tid, score, motivo in resultados:
        res = await db.execute(
            select(Recomendacao).where(
                Recomendacao.usuario_id  == usuario_id,
                Recomendacao.topico_id   == tid,
                Recomendacao.visualizada == False,
            )
        )
        antiga = res.scalar_one_or_none()
        if antiga:
            antiga.score_relevancia = score
            antiga.motivo           = motivo
            antiga.gerada_em        = datetime.now(timezone.utc)
            novas.append(antiga)
        else:
            rec = Recomendacao(
                usuario_id=usuario_id,
                topico_id=tid,
                score_relevancia=score,
                motivo=motivo,
            )
            db.add(rec)
            novas.append(rec)

    await db.flush()
    return novas
