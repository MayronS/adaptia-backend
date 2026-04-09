from datetime import datetime, timedelta, timezone
import uuid
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    VinculoProfessorAluno, StatusVinculo,
    Usuario, Materia, Topico, Quiz, Questao, Alternativa,
    ProgressoTopico, TentativaQuiz, RespostaQuestao,
    Recomendacao, StatusProgresso
)
from app.schemas.schemas import (
    DashboardAlunoOut, UsuarioOut, ProgressoOut,
    RecomendacaoOut, TopicoComProgressoOut, MateriaOut,
    QuizComQuestoesOut, QuestaoOut, AlternativaOut,
    TentativaCreate, TentativaOut, RespostaQuestaoOut,
    AlternativaComGabaritoOut, MelhorTentativaOut,
    ConviteOut, ResponderConviteRequest,
)
from app.services.auth_service import require_aluno
from app.services.recomendacao_service import gerar_recomendacoes

router = APIRouter(prefix="/aluno", tags=["aluno"])

# Número de questões sorteadas por quiz a cada tentativa
# Pontuação mínima (%) para concluir tópico e desbloquear o próximo
THRESHOLD_APROVACAO = 75


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardAlunoOut)
async def dashboard(
    user: Usuario    = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    # Progressos
    res = await db.execute(
        select(ProgressoTopico).where(ProgressoTopico.usuario_id == user.id)
    )
    progressos = res.scalars().all()

    # Tentativas para calcular métricas
    res = await db.execute(
        select(TentativaQuiz).where(TentativaQuiz.usuario_id == user.id)
    )
    tentativas = res.scalars().all()

    pontuacao_geral  = round(sum(p.pontuacao for p in progressos) / max(len(progressos), 1), 1)
    total_exercicios = sum(t.total_questoes for t in tentativas)
    acertos_total    = sum(t.acertos for t in tentativas)
    taxa_acerto      = round(acertos_total / max(total_exercicios, 1) * 100, 1)

    hoje = datetime.now(timezone.utc).date()

    # Sequência de dias consecutivos com estudo
    datas = sorted({t.realizado_em.date() for t in tentativas}, reverse=True)
    sequencia = 0
    for i, data in enumerate(datas):
        if data == hoje - timedelta(days=i):
            sequencia += 1
        else:
            break

    # Maior sequência histórica
    melhor_sequencia = 0
    sequencia_atual  = 0
    for i, data in enumerate(datas):
        if i == 0 or data == datas[i-1] - timedelta(days=1):
            sequencia_atual += 1
            melhor_sequencia = max(melhor_sequencia, sequencia_atual)
        else:
            sequencia_atual = 1

    # Acertos reais dos últimos 7 dias (índice 0 = 6 dias atrás, índice 6 = hoje)
    acertos_semana = [0] * 7
    exercicios_semana = 0
    for t in tentativas:
        data_tent = t.realizado_em.date()
        diff = (hoje - data_tent).days
        if 0 <= diff <= 6:
            acertos_semana[6 - diff] += t.acertos
            exercicios_semana += t.total_questoes

    # Recomendações ativas
    res = await db.execute(
        select(Recomendacao)
        .options(selectinload(Recomendacao.topico).selectinload(Topico.materia))
        .where(Recomendacao.usuario_id == user.id, Recomendacao.visualizada == False)
        .order_by(Recomendacao.score_relevancia.desc())
        .limit(5)
    )
    recomendacoes = res.scalars().all()

    return DashboardAlunoOut(
        usuario=UsuarioOut.from_usuario(user),
        pontuacao_geral=pontuacao_geral,
        taxa_acerto_pct=taxa_acerto,
        total_exercicios=total_exercicios,
        sequencia_dias=sequencia,
        melhor_sequencia=melhor_sequencia,
        acertos_semana=acertos_semana,
        exercicios_semana=exercicios_semana,
        progressos=[ProgressoOut.model_validate(p) for p in progressos],
        recomendacoes=[RecomendacaoOut.model_validate(r) for r in recomendacoes],
    )


# ── Matérias e Tópicos ────────────────────────────────────────────────────────

@router.get("/topicos", response_model=list[TopicoComProgressoOut])
async def listar_topicos(
    materia_id: uuid.UUID | None = None,
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Lista apenas os tópicos que o aluno adicionou explicitamente."""
    # Busca IDs dos tópicos que o aluno tem progresso
    res = await db.execute(
        select(ProgressoTopico).where(ProgressoTopico.usuario_id == user.id)
    )
    progressos = res.scalars().all()

    if not progressos:
        return []

    prog_map = {p.topico_id: p for p in progressos}
    topico_ids = list(prog_map.keys())

    # Busca os tópicos com matéria carregada
    query = (
        select(Topico)
        .options(selectinload(Topico.materia))
        .where(Topico.id.in_(topico_ids), Topico.ativo == True)
        .order_by(Topico.ordem)
    )
    if materia_id:
        query = query.where(Topico.materia_id == materia_id)

    res = await db.execute(query)
    topicos = res.scalars().all()

    resultado = []
    for t in topicos:
        prog = prog_map[t.id]
        item = TopicoComProgressoOut.model_validate(t)
        item.status    = prog.status
        item.pontuacao = prog.pontuacao
        resultado.append(item)

    return resultado


# ── Matérias ──────────────────────────────────────────────────────────────────

@router.get("/materias", response_model=list[MateriaOut])
async def listar_materias(
    user: Usuario    = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Lista todas as matérias disponíveis na plataforma."""
    res = await db.execute(select(Materia).where(Materia.ativo == True).order_by(Materia.ordem))
    return res.scalars().all()


@router.post("/materias/{materia_id}/adicionar", status_code=201)
async def adicionar_materia(
    materia_id: uuid.UUID,
    user: Usuario    = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Inicializa o progresso do aluno em todos os tópicos de uma matéria."""
    # Verifica se matéria existe
    res = await db.execute(select(Materia).where(Materia.id == materia_id, Materia.ativo == True))
    materia = res.scalar_one_or_none()
    if not materia:
        raise HTTPException(status_code=404, detail="Matéria não encontrada")

    # Busca tópicos da matéria
    res = await db.execute(
        select(Topico).where(Topico.materia_id == materia_id, Topico.ativo == True).order_by(Topico.ordem)
    )
    topicos = res.scalars().all()

    # Busca progressos já existentes para esses tópicos
    topico_ids = [t.id for t in topicos]
    res = await db.execute(
        select(ProgressoTopico).where(
            ProgressoTopico.usuario_id == user.id,
            ProgressoTopico.topico_id.in_(topico_ids),
        )
    )
    existentes = {p.topico_id for p in res.scalars().all()}

    # Cria progresso apenas para os tópicos que ainda não têm
    criados = 0
    for topico in topicos:
        if topico.id not in existentes:
            status_inicial = (
                StatusProgresso.disponivel
                if topico.prerequisito_id is None
                else StatusProgresso.bloqueado
            )
            db.add(ProgressoTopico(
                usuario_id=user.id,
                topico_id=topico.id,
                status=status_inicial,
            ))
            criados += 1

    return {"ok": True, "materia": materia.nome, "topicos_adicionados": criados}


# ── Quiz ──────────────────────────────────────────────────────────────────────

@router.get("/topicos/{topico_id}/quizzes", response_model=list[QuizComQuestoesOut])
async def listar_quizzes_topico(
    topico_id: uuid.UUID,
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    # Verifica se o aluno tem acesso ao tópico
    res = await db.execute(
        select(ProgressoTopico).where(
            ProgressoTopico.usuario_id == user.id,
            ProgressoTopico.topico_id  == topico_id,
            ProgressoTopico.status.in_([
                StatusProgresso.disponivel,
                StatusProgresso.em_progresso,
                StatusProgresso.concluido,
            ])
        )
    )
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Tópico bloqueado. Conclua o pré-requisito primeiro.")

    res = await db.execute(
        select(Quiz)
        .options(
            selectinload(Quiz.questoes).selectinload(Questao.alternativas)
        )
        .where(Quiz.topico_id == topico_id, Quiz.ativo == True)
    )
    quizzes = res.scalars().all()

    # Monta resposta sem gabarito — sorteia 4 questões aleatórias de todas as disponíveis
    resultado = []
    for q in quizzes:
        questoes_ativas = [quest for quest in q.questoes if quest.ativo]

        # Usa o campo do quiz; se None, usa todas as questões ativas
        n = q.questoes_por_tentativa if q.questoes_por_tentativa else len(questoes_ativas)
        selecionadas = random.sample(questoes_ativas, min(n, len(questoes_ativas)))

        q_out = QuizComQuestoesOut.model_validate(q)
        q_out.questoes = [
            QuestaoOut(
                id=quest.id,
                enunciado=quest.enunciado,
                tipo=quest.tipo,
                pontos=quest.pontos,
                ordem=i + 1,  # renumera a ordem após o sorteio
                alternativas=[AlternativaOut.model_validate(a) for a in random.sample(quest.alternativas, len(quest.alternativas))]
            )
            for i, quest in enumerate(selecionadas)
        ]
        resultado.append(q_out)

    return resultado


# ── Tentativa ─────────────────────────────────────────────────────────────────

@router.post("/tentativas", response_model=TentativaOut, status_code=201)
async def submeter_tentativa(
    body: TentativaCreate,
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Recebe as respostas do aluno, calcula pontuação e atualiza progresso."""
    # Carrega quiz com questões e alternativas
    res = await db.execute(
        select(Quiz)
        .options(selectinload(Quiz.questoes).selectinload(Questao.alternativas))
        .where(Quiz.id == body.quiz_id, Quiz.ativo == True)
    )
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    # Verifica limite de tentativas
    if quiz.tentativas_max:
        res = await db.execute(
            select(func.count(TentativaQuiz.id)).where(
                TentativaQuiz.usuario_id == user.id,
                TentativaQuiz.quiz_id    == quiz.id,
            )
        )
        count = res.scalar_one()
        if count >= quiz.tentativas_max:
            raise HTTPException(status_code=400, detail="Limite de tentativas atingido")

    # Mapa questão_id → alternativa correta
    gabarito: dict[uuid.UUID, uuid.UUID] = {}
    alt_map:  dict[uuid.UUID, Alternativa] = {}
    for q in quiz.questoes:
        for a in q.alternativas:
            alt_map[a.id] = a
            if a.correta:
                gabarito[q.id] = a.id

    # Calcula acertos
    acertos = 0
    pontuacao_total = 0
    respostas_db: list[RespostaQuestao] = []

    questao_map = {q.id: q for q in quiz.questoes}

    for resp in body.respostas:
        questao = questao_map.get(resp.questao_id)
        if not questao:
            continue
        correta = resp.alternativa_id is not None and gabarito.get(resp.questao_id) == resp.alternativa_id
        if correta:
            acertos          += 1
            pontuacao_total  += questao.pontos

        respostas_db.append(RespostaQuestao(
            questao_id=resp.questao_id,
            alternativa_id=resp.alternativa_id,
            resposta_texto=resp.resposta_texto,
            correta=correta,
            tempo_resposta_seg=resp.tempo_resposta_seg,
        ))

    # Normaliza pontuação sempre em base 100 sobre as questões SORTEADAS (respondidas)
    # Garante que 3/4 acertos = 75% independente do pontuacao_maxima do quiz no banco
    total_pontos_respondidos = sum(
        questao_map[r.questao_id].pontos
        for r in respostas_db
        if r.questao_id in questao_map
    ) or 1
    pontuacao_100 = round(pontuacao_total / total_pontos_respondidos * 100)

    # Cria tentativa
    tentativa = TentativaQuiz(
        usuario_id=user.id,
        quiz_id=quiz.id,
        pontuacao=pontuacao_100,
        acertos=acertos,
        total_questoes=len(respostas_db),  # questões efetivamente respondidas (sorteadas)
        tempo_gasto_seg=body.tempo_gasto_seg,
    )
    db.add(tentativa)
    await db.flush()

    for r in respostas_db:
        r.tentativa_id = tentativa.id
        db.add(r)

    # Incrementa contadores de acertos/erros por questão (para análise de dados)
    for r in respostas_db:
        if r.correta:
            await db.execute(
                update(Questao)
                .where(Questao.id == r.questao_id)
                .values(total_acertos=Questao.total_acertos + 1)
            )
        else:
            await db.execute(
                update(Questao)
                .where(Questao.id == r.questao_id)
                .values(total_erros=Questao.total_erros + 1)
            )

    # Atualiza progresso do tópico
    res = await db.execute(
        select(ProgressoTopico).where(
            ProgressoTopico.usuario_id == user.id,
            ProgressoTopico.topico_id  == quiz.topico_id,
        )
    )
    progresso = res.scalar_one_or_none()
    if progresso:
        if progresso.status == StatusProgresso.disponivel:
            progresso.status      = StatusProgresso.em_progresso
            progresso.iniciado_em = datetime.now(timezone.utc)

        # Busca todos os quizzes do tópico
        res_quizzes = await db.execute(
            select(Quiz).where(Quiz.topico_id == quiz.topico_id, Quiz.ativo == True)
        )
        todos_quizzes = res_quizzes.scalars().all()
        total_quizzes_topico = len(todos_quizzes)

        # Busca a melhor tentativa de cada quiz do tópico para este aluno
        res_tent = await db.execute(
            select(TentativaQuiz).where(
                TentativaQuiz.usuario_id == user.id,
                TentativaQuiz.quiz_id.in_([q.id for q in todos_quizzes]),
            )
        )
        todas_tent = res_tent.scalars().all()

        # Agrupa por quiz_id, mantém a maior pontuação
        melhores_por_quiz: dict[uuid.UUID, int] = {}
        for t in todas_tent:
            atual = melhores_por_quiz.get(t.quiz_id, 0)
            if t.pontuacao > atual:
                melhores_por_quiz[t.quiz_id] = t.pontuacao

        # Inclui a tentativa atual (ainda não persistida, mas já calculada)
        melhores_por_quiz[quiz.id] = max(melhores_por_quiz.get(quiz.id, 0), pontuacao_100)

        # Média das melhores pontuações sobre TODOS os quizzes do tópico
        soma = sum(melhores_por_quiz.get(q.id, 0) for q in todos_quizzes)
        media_topico = round(soma / total_quizzes_topico) if total_quizzes_topico > 0 else 0

        progresso.pontuacao = media_topico

        # Conclui o tópico somente quando a média geral >= THRESHOLD_APROVACAO (75%)
        if media_topico >= THRESHOLD_APROVACAO:
            progresso.status       = StatusProgresso.concluido
            progresso.concluido_em = datetime.now(timezone.utc)
            await _desbloquear_proximos(user.id, quiz.topico_id, db)
        else:
            # Garante que volta para em_progresso se a média caiu abaixo do threshold
            if progresso.status == StatusProgresso.concluido:
                progresso.status       = StatusProgresso.em_progresso
                progresso.concluido_em = None

    # Gera novas recomendações após a tentativa
    await gerar_recomendacoes(user.id, db)

    # Monta resposta com gabarito
    respostas_out = []
    for r in respostas_db:
        alt_correta = alt_map.get(gabarito.get(r.questao_id))
        respostas_out.append(RespostaQuestaoOut(
            questao_id=r.questao_id,
            alternativa_id=r.alternativa_id,
            correta=r.correta,
            tempo_resposta_seg=r.tempo_resposta_seg,
            alternativa_correta=AlternativaComGabaritoOut.model_validate(alt_correta) if alt_correta else None,
        ))

    return TentativaOut(
        id=tentativa.id,
        quiz_id=tentativa.quiz_id,
        pontuacao=tentativa.pontuacao,
        acertos=tentativa.acertos,
        total_questoes=tentativa.total_questoes,
        tempo_gasto_seg=tentativa.tempo_gasto_seg,
        realizado_em=tentativa.realizado_em,
        respostas=respostas_out,
    )


# ── Recomendações ─────────────────────────────────────────────────────────────

@router.post("/recomendacoes/gerar")
async def forcar_recomendacoes(
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Força regeneração das recomendações para o aluno logado."""
    recs = await gerar_recomendacoes(user.id, db)
    return {"geradas": len(recs)}


@router.patch("/recomendacoes/{rec_id}/visualizar")
async def marcar_visualizada(
    rec_id: uuid.UUID,
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Recomendacao).where(
            Recomendacao.id == rec_id,
            Recomendacao.usuario_id == user.id,
        )
    )
    rec = res.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recomendação não encontrada")
    rec.visualizada = True
    return {"ok": True}


# ── Melhores tentativas por quiz ──────────────────────────────────────────────

@router.get("/tentativas/melhores", response_model=list[MelhorTentativaOut])
async def melhores_tentativas(
    user: Usuario      = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Retorna a melhor tentativa de cada quiz para o aluno logado."""
    res = await db.execute(
        select(TentativaQuiz).where(TentativaQuiz.usuario_id == user.id)
    )
    todas = res.scalars().all()

    # Agrupa por quiz_id mantendo a de maior pontuação
    melhores: dict[uuid.UUID, TentativaQuiz] = {}
    for t in todas:
        atual = melhores.get(t.quiz_id)
        if atual is None or t.pontuacao > atual.pontuacao:
            melhores[t.quiz_id] = t

    return [
        MelhorTentativaOut(
            quiz_id=t.quiz_id,
            pontuacao=t.pontuacao,
            acertos=t.acertos,
            total_questoes=t.total_questoes,
            aprovado=t.pontuacao >= THRESHOLD_APROVACAO,
        )
        for t in melhores.values()
    ]


# ── Helper interno ────────────────────────────────────────────────────────────

async def _desbloquear_proximos(usuario_id: uuid.UUID, topico_concluido_id: uuid.UUID, db: AsyncSession):
    """Desbloqueia os tópicos cujo pré-requisito acabou de ser concluído."""
    res = await db.execute(
        select(Topico).where(Topico.prerequisito_id == topico_concluido_id, Topico.ativo == True)
    )
    proximos = res.scalars().all()
    for prox in proximos:
        res2 = await db.execute(
            select(ProgressoTopico).where(
                ProgressoTopico.usuario_id == usuario_id,
                ProgressoTopico.topico_id  == prox.id,
            )
        )
        prog = res2.scalar_one_or_none()
        if prog and prog.status == StatusProgresso.bloqueado:
            prog.status = StatusProgresso.disponivel

# ══════════════════════════════════════════════════════════════════════════════
# CONVITES DO PROFESSOR (visão do aluno)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/convites", response_model=list[ConviteOut])
async def listar_convites(
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Retorna convites pendentes e histórico para o aluno."""
    res = await db.execute(
        select(VinculoProfessorAluno)
        .options(selectinload(VinculoProfessorAluno.professor).selectinload(Usuario.perfis))
        .where(VinculoProfessorAluno.aluno_id == user.id)
        .order_by(VinculoProfessorAluno.criado_em.desc())
    )
    return res.scalars().all()


@router.patch("/convites/{vinculo_id}/responder")
async def responder_convite(
    vinculo_id: uuid.UUID,
    body: ResponderConviteRequest,
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Aluno aceita ou recusa convite de orientação."""
    res = await db.execute(
        select(VinculoProfessorAluno).where(
            VinculoProfessorAluno.id       == vinculo_id,
            VinculoProfessorAluno.aluno_id == user.id,
        )
    )
    vinculo = res.scalar_one_or_none()
    if not vinculo:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    if vinculo.status != StatusVinculo.pendente:
        raise HTTPException(status_code=400, detail="Este convite já foi respondido")

    vinculo.status       = StatusVinculo.aceito if body.aceitar else StatusVinculo.recusado
    vinculo.respondido_em = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(vinculo)
    return {"status": vinculo.status, "mensagem": "Convite aceito!" if body.aceitar else "Convite recusado."}

# ══════════════════════════════════════════════════════════════════════════════
# ANÁLISE DE ERROS + QUIZ IA (Gemini)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/analise-erros")
async def analise_erros(
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """
    Analisa as tentativas do aluno e retorna os tópicos com pior desempenho,
    ordenados por taxa de erro, com dados suficientes para gerar quizzes de revisão.
    """
    from sqlalchemy.orm import selectinload as sil
    from app.models.models import Topico

    # Busca todas as tentativas com respostas
    res = await db.execute(
        select(TentativaQuiz)
        .options(
            sil(TentativaQuiz.quiz).selectinload(Quiz.topico).selectinload(Topico.materia),
            sil(TentativaQuiz.respostas),
        )
        .where(TentativaQuiz.usuario_id == user.id)
    )
    tentativas = res.scalars().all()

    if not tentativas:
        return {"topicos_fracos": [], "total_tentativas": 0}

    # Agrupa por tópico
    from collections import defaultdict
    por_topico: dict = defaultdict(lambda: {"acertos": 0, "total": 0, "topico": None, "materia": None, "nivel": 1})

    for t in tentativas:
        if not t.quiz or not t.quiz.topico:
            continue
        tid = t.quiz.topico_id
        por_topico[tid]["acertos"] += t.acertos
        por_topico[tid]["total"]   += t.total_questoes
        por_topico[tid]["topico"]  = t.quiz.topico.titulo
        por_topico[tid]["materia"] = t.quiz.topico.materia.nome if t.quiz.topico.materia else "Geral"
        por_topico[tid]["nivel"]   = t.quiz.topico.nivel_dificuldade
        por_topico[tid]["topico_id"] = str(tid)

    # Calcula taxa de erro e filtra tópicos com pelo menos 3 questões respondidas
    resultados = []
    for tid, dados in por_topico.items():
        if dados["total"] < 3:
            continue
        taxa_acerto = round(dados["acertos"] / dados["total"] * 100, 1)
        taxa_erro   = round(100 - taxa_acerto, 1)
        resultados.append({
            "topico_id":   dados["topico_id"],
            "topico":      dados["topico"],
            "materia":     dados["materia"],
            "nivel":       dados["nivel"],
            "taxa_acerto": taxa_acerto,
            "taxa_erro":   taxa_erro,
            "total_respondidas": dados["total"],
        })

    # Ordena por maior taxa de erro, pega top 5
    resultados.sort(key=lambda x: x["taxa_erro"], reverse=True)
    topicos_fracos = resultados[:5]

    return {
        "topicos_fracos": topicos_fracos,
        "total_tentativas": len(tentativas),
    }


@router.post("/quiz-ia")
async def gerar_quiz_ia(
    body: dict,
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """
    Recebe um tópico fraco e chama o Gemini para gerar 5 questões de revisão.
    Retorna o quiz completo sem persistir no banco.
    """
    from app.services.gemini_service import gerar_quiz_topico

    topico_nome = body.get("topico", "")
    materia_nome = body.get("materia", "")
    nivel = body.get("nivel", 1)

    if not topico_nome:
        raise HTTPException(status_code=400, detail="topico é obrigatório")

    try:
        questoes = await gerar_quiz_topico(topico_nome, materia_nome, nivel, n_questoes=5)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Erro inesperado no quiz-ia: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Erro interno ao gerar quiz: {str(e)}")

    # Monta o quiz no formato do frontend
    quiz = {
        "id": f"ia_{topico_nome.replace(' ', '_')}",
        "titulo": f"Revisão — {topico_nome}",
        "topico": topico_nome,
        "materia": materia_nome,
        "gerado_por_ia": True,
        "questoes": [
            {
                "id": f"q_{i}",
                "enunciado": q["enunciado"],
                "tipo": "multipla_escolha",
                "alternativas": [
                    {
                        "id": f"q_{i}_a_{j}",
                        "texto": a["texto"],
                        "correta": a.get("correta", False),
                        "explicacao": a.get("explicacao", ""),
                    }
                    for j, a in enumerate(q.get("alternativas", []))
                ],
            }
            for i, q in enumerate(questoes)
        ],
    }
    return quiz


# ══════════════════════════════════════════════════════════════════════════════
# QUIZ DIÁRIO
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/quiz-diario")
async def get_quiz_diario(
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """
    Retorna o quiz diário do aluno:
    - Identifica o tópico com maior taxa de erro real
    - Sorteia 5 questões aleatórias desse tópico
    - Se não houver tentativas ainda, usa o primeiro tópico disponível
    """
    from collections import defaultdict
    from app.models.models import Topico

    # ── 1. Busca tentativas do aluno para calcular taxa de erro por tópico ──
    res = await db.execute(
        select(TentativaQuiz)
        .options(selectinload(TentativaQuiz.quiz))
        .where(TentativaQuiz.usuario_id == user.id)
    )
    tentativas = res.scalars().all()

    acertos_por_topico: dict = defaultdict(int)
    total_por_topico:   dict = defaultdict(int)

    for t in tentativas:
        if t.quiz:
            tid = t.quiz.topico_id
            acertos_por_topico[tid] += t.acertos
            total_por_topico[tid]   += t.total_questoes

    # ── 2. Tópicos disponíveis/em_progresso ──
    res = await db.execute(
        select(ProgressoTopico)
        .options(selectinload(ProgressoTopico.topico))
        .where(
            ProgressoTopico.usuario_id == user.id,
            ProgressoTopico.status.in_([StatusProgresso.disponivel, StatusProgresso.em_progresso]),
        )
    )
    progressos = res.scalars().all()

    if not progressos:
        return {"disponivel": False, "motivo": "Nenhum tópico disponível ainda."}

    # ── 3. Escolhe o tópico com maior taxa de erro (ou o primeiro se sem dados) ──
    melhor_topico_id = None
    maior_taxa_erro  = -1.0

    for p in progressos:
        tid   = p.topico_id
        total = total_por_topico.get(tid, 0)
        if total == 0:
            taxa_erro = 0.5  # nunca tentado → score médio
        else:
            taxa_erro = 1.0 - acertos_por_topico.get(tid, 0) / total

        if taxa_erro > maior_taxa_erro:
            maior_taxa_erro  = taxa_erro
            melhor_topico_id = tid
            melhor_topico    = p.topico

    if not melhor_topico_id:
        return {"disponivel": False, "motivo": "Nenhum tópico elegível."}

    # ── 4. Busca quizzes do tópico com questões ──
    res = await db.execute(
        select(Quiz)
        .options(selectinload(Quiz.questoes).selectinload(Questao.alternativas))
        .where(Quiz.topico_id == melhor_topico_id, Quiz.ativo == True)
    )
    quizzes = res.scalars().all()

    # Junta todas as questões ativas de todos os quizzes do tópico
    todas_questoes = []
    for q in quizzes:
        todas_questoes.extend([quest for quest in q.questoes if quest.ativo])

    if not todas_questoes:
        return {"disponivel": False, "motivo": "Nenhuma questão disponível para o tópico recomendado."}

    # ── 5. Sorteia até 5 questões ──
    selecionadas = random.sample(todas_questoes, min(5, len(todas_questoes)))

    taxa_acerto_pct = round((1.0 - maior_taxa_erro) * 100, 1) if maior_taxa_erro != 0.5 else None

    return {
        "disponivel":     True,
        "topico_id":      str(melhor_topico_id),
        "topico_nome":    melhor_topico.titulo if melhor_topico else "",
        "taxa_erro_pct":  round(maior_taxa_erro * 100, 1) if maior_taxa_erro != 0.5 else None,
        "taxa_acerto_pct": taxa_acerto_pct,
        "questoes": [
            {
                "id": str(q.id),
                "enunciado": q.enunciado,
                "tipo": q.tipo,
                "alternativas": [
                    {
                        "id":    str(a.id),
                        "texto": a.texto,
                        "correta": a.correta,
                    }
                    for a in random.sample(q.alternativas, len(q.alternativas))
                ],
            }
            for q in selecionadas
        ],
    }