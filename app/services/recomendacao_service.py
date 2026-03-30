"""
Motor de recomendação da AdaptIA
─────────────────────────────────
Combina duas estratégias:

1. Filtragem por conteúdo
   Considera o nível de dificuldade do tópico vs. desempenho do aluno.
   Tópicos disponíveis com dificuldade próxima ao nível atual do aluno
   recebem score mais alto.

2. Filtragem colaborativa (user-based)
   Calcula similaridade de cosseno entre o vetor de pontuações do aluno
   e os vetores dos demais alunos. Tópicos que alunos similares concluíram
   (e que o aluno atual ainda não fez) recebem bônus de score.

Score final = 0.6 × score_conteudo + 0.4 × score_colaborativo
"""

import uuid
import numpy as np
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sklearn.metrics.pairwise import cosine_similarity

from app.models.models import (
    Topico, ProgressoTopico, TentativaQuiz, Quiz,
    Recomendacao, StatusProgresso
)


PESO_CONTEUDO      = 0.6
PESO_COLABORATIVO  = 0.4
MIN_SCORE          = 0.05
TOP_N              = 5        # quantas recomendações gerar


async def gerar_recomendacoes(usuario_id: uuid.UUID, db: AsyncSession) -> list[Recomendacao]:
    """Gera (ou atualiza) as recomendações para um aluno."""

    # ── 1. Busca todos os tópicos disponíveis/em_progresso para o aluno ────────
    res = await db.execute(
        select(ProgressoTopico)
        .where(
            ProgressoTopico.usuario_id == usuario_id,
            ProgressoTopico.status.in_([StatusProgresso.disponivel, StatusProgresso.em_progresso])
        )
    )
    progressos_aluno = res.scalars().all()

    if not progressos_aluno:
        return []

    topico_ids_candidatos = [p.topico_id for p in progressos_aluno]

    # ── 2. Busca detalhes dos tópicos candidatos ────────────────────────────────
    res = await db.execute(select(Topico).where(Topico.id.in_(topico_ids_candidatos)))
    topicos = {t.id: t for t in res.scalars().all()}

    # ── 3. Nível atual do aluno (média ponderada das pontuações) ────────────────
    pontuacoes_aluno = {p.topico_id: p.pontuacao for p in progressos_aluno}
    nivel_aluno = np.mean(list(pontuacoes_aluno.values())) / 20  # normaliza 0-100 → 0-5

    # ── 4. Score por conteúdo ───────────────────────────────────────────────────
    scores_conteudo: dict[uuid.UUID, float] = {}
    for tid, topico in topicos.items():
        diff = abs(topico.nivel_dificuldade - nivel_aluno)
        scores_conteudo[tid] = max(0.0, 1.0 - diff / 5)

    # ── 5. Score colaborativo ───────────────────────────────────────────────────
    scores_colab: dict[uuid.UUID, float] = {tid: 0.0 for tid in topico_ids_candidatos}

    # Busca pontuações de todos os alunos em todos os tópicos candidatos
    res = await db.execute(
        select(ProgressoTopico)
        .where(ProgressoTopico.topico_id.in_(topico_ids_candidatos))
    )
    todos_progressos = res.scalars().all()

    # Monta matriz usuário × tópico
    usuarios_ids = list({p.usuario_id for p in todos_progressos})
    topicos_ids  = topico_ids_candidatos

    if len(usuarios_ids) > 1:
        u_idx = {u: i for i, u in enumerate(usuarios_ids)}
        t_idx = {t: i for i, t in enumerate(topicos_ids)}

        matriz = np.zeros((len(usuarios_ids), len(topicos_ids)))
        for p in todos_progressos:
            matriz[u_idx[p.usuario_id], t_idx[p.topico_id]] = p.pontuacao

        if usuario_id in u_idx:
            idx_aluno = u_idx[usuario_id]
            vetor_aluno = matriz[idx_aluno].reshape(1, -1)

            # Similaridade com todos os outros usuários
            sims = cosine_similarity(vetor_aluno, matriz)[0]

            for i, sim in enumerate(sims):
                if usuarios_ids[i] == usuario_id or sim < 0.1:
                    continue
                # Tópicos que esse usuário similar concluiu
                for p in todos_progressos:
                    if (p.usuario_id == usuarios_ids[i]
                            and p.status == StatusProgresso.concluido
                            and p.topico_id in t_idx):
                        scores_colab[p.topico_id] = max(
                            scores_colab[p.topico_id], sim
                        )

    # ── 6. Score final e motivo ─────────────────────────────────────────────────
    resultados: list[tuple[uuid.UUID, float, str]] = []
    for tid in topico_ids_candidatos:
        sc = scores_conteudo.get(tid, 0)
        collab = scores_colab.get(tid, 0)
        score_final = PESO_CONTEUDO * sc + PESO_COLABORATIVO * collab

        if score_final < MIN_SCORE:
            continue

        # Define motivo legível
        if pontuacoes_aluno.get(tid, 0) < 40:
            motivo = "dificuldade detectada"
        elif collab > sc:
            motivo = "alunos similares avançaram aqui"
        else:
            motivo = "sequência natural de aprendizado"

        resultados.append((tid, round(score_final, 4), motivo))

    # Ordena e pega top N
    resultados.sort(key=lambda x: x[1], reverse=True)
    resultados = resultados[:TOP_N]

    # ── 7. Persiste recomendações (upsert simples) ──────────────────────────────
    novas: list[Recomendacao] = []
    for tid, score, motivo in resultados:
        # Remove recomendação antiga não visualizada para o mesmo tópico
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
            antiga.gerada_em        = datetime.utcnow()
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
