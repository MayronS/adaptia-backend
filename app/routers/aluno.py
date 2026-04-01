from datetime import datetime, timedelta
import uuid
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
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
)
from app.services.auth_service import require_aluno
from app.services.recomendacao_service import gerar_recomendacoes

router = APIRouter(prefix="/aluno", tags=["aluno"])

# Número de questões sorteadas por quiz a cada tentativa
QUESTOES_POR_QUIZ = 4

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

    # Sequência de dias consecutivos com estudo
    datas = sorted({t.realizado_em.date() for t in tentativas}, reverse=True)
    sequencia = 0
    hoje = datetime.utcnow().date()
    for i, data in enumerate(datas):
        if data == hoje - timedelta(days=i):
            sequencia += 1
        else:
            break

    # Recomendações ativas
    res = await db.execute(
        select(Recomendacao)
        .options(selectinload(Recomendacao.topico))
        .where(Recomendacao.usuario_id == user.id, Recomendacao.visualizada == False)
        .order_by(Recomendacao.score_relevancia.desc())
        .limit(5)
    )
    recomendacoes = res.scalars().all()

    return DashboardAlunoOut(
        usuario=UsuarioOut.model_validate(user),
        pontuacao_geral=pontuacao_geral,
        taxa_acerto_pct=taxa_acerto,
        total_exercicios=total_exercicios,
        sequencia_dias=sequencia,
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
    """Lista tópicos com o status de progresso do aluno."""
    query = select(Topico).where(Topico.ativo == True)
    if materia_id:
        query = query.where(Topico.materia_id == materia_id)
    query = query.order_by(Topico.ordem).options(selectinload(Topico.materia))

    res     = await db.execute(query)
    topicos = res.scalars().all()

    # Busca progressos existentes do aluno
    res = await db.execute(
        select(ProgressoTopico).where(ProgressoTopico.usuario_id == user.id)
    )
    prog_map = {p.topico_id: p for p in res.scalars().all()}

    # Cria progresso para tópicos novos que ainda não têm registro
    novos = []
    for t in topicos:
        if t.id not in prog_map:
            status_inicial = (
                StatusProgresso.disponivel
                if t.prerequisito_id is None
                else StatusProgresso.bloqueado
            )
            novo = ProgressoTopico(
                usuario_id=user.id,
                topico_id=t.id,
                status=status_inicial,
            )
            db.add(novo)
            novos.append((t.id, novo))

    if novos:
        await db.flush()
        for topico_id, novo in novos:
            prog_map[topico_id] = novo

    resultado = []
    for t in topicos:
        prog = prog_map.get(t.id)
        item = TopicoComProgressoOut.model_validate(t)
        item.status    = prog.status    if prog else None
        item.pontuacao = prog.pontuacao if prog else None
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
    QUESTOES_POR_QUIZ = 4

    resultado = []
    for q in quizzes:
        questoes_ativas = [quest for quest in q.questoes if quest.ativo]

        # Sorteia até QUESTOES_POR_QUIZ questões aleatórias sem repetição
        selecionadas = random.sample(questoes_ativas, min(QUESTOES_POR_QUIZ, len(questoes_ativas)))

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

    # Normaliza pontuação sobre as questões SORTEADAS (respondidas), não o banco completo
    # Garante que 3/4 acertos = 75%, independente de ter 10 questões no banco
    total_pontos_respondidos = sum(
        questao_map[r.questao_id].pontos
        for r in respostas_db
        if r.questao_id in questao_map
    ) or 1
    pontuacao_100 = round(pontuacao_total / total_pontos_respondidos * quiz.pontuacao_maxima)

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
            progresso.iniciado_em = datetime.utcnow()
        if pontuacao_100 > progresso.pontuacao:
            progresso.pontuacao = pontuacao_100
        if pontuacao_100 >= THRESHOLD_APROVACAO:  # 75%
            progresso.status       = StatusProgresso.concluido
            progresso.concluido_em = datetime.utcnow()
            # Desbloqueia tópicos que dependiam deste
            await _desbloquear_proximos(user.id, quiz.topico_id, db)

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