import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    Materia, Topico, Quiz, Questao, Alternativa,
    ProgressoTopico, StatusProgresso, Usuario, UsuarioPerfil, PerfilUsuario,
)
from app.schemas.schemas import (
    MateriaCreate, MateriaOut,
    TopicoCreate, TopicoOut,
    QuizCreate, QuizOut, QuizComQuestoesOut,
    QuestaoCreate, QuestaoOut,
    AlternativaCreate, AlternativaOut,
)
from app.services.auth_service import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ══════════════════════════════════════════════════════════════════════════════
# MATÉRIAS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/materias", response_model=list[MateriaOut])
async def listar_materias(
    _:  Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).order_by(Materia.ordem, Materia.nome))
    return res.scalars().all()


@router.post("/materias", response_model=MateriaOut, status_code=201)
async def criar_materia(
    body: MateriaCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    existe = await db.execute(select(Materia).where(Materia.nome == body.nome))
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Já existe uma matéria com esse nome")

    materia = Materia(**body.model_dump())
    db.add(materia)
    await db.commit()
    await db.refresh(materia)
    return materia


@router.put("/materias/{materia_id}", response_model=MateriaOut)
async def editar_materia(
    materia_id: uuid.UUID,
    body: MateriaCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.id == materia_id))
    materia = res.scalar_one_or_none()
    if not materia:
        raise HTTPException(status_code=404, detail="Matéria não encontrada")

    for k, v in body.model_dump().items():
        setattr(materia, k, v)
    await db.commit()
    await db.refresh(materia)
    return materia


@router.delete("/materias/{materia_id}", status_code=204)
async def deletar_materia(
    materia_id: uuid.UUID,
    _:  Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.id == materia_id))
    materia = res.scalar_one_or_none()
    if not materia:
        raise HTTPException(status_code=404, detail="Matéria não encontrada")
    await db.delete(materia)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# TÓPICOS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/materias/{materia_id}/topicos", response_model=list[TopicoOut])
async def listar_topicos(
    materia_id: uuid.UUID,
    _:  Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico)
        .options(selectinload(Topico.materia))
        .where(Topico.materia_id == materia_id)
        .order_by(Topico.ordem, Topico.titulo)
    )
    return res.scalars().all()


@router.post("/materias/{materia_id}/topicos", response_model=TopicoOut, status_code=201)
async def criar_topico(
    materia_id: uuid.UUID,
    body: TopicoCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.id == materia_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Matéria não encontrada")

    topico = Topico(materia_id=materia_id, **body.model_dump())
    db.add(topico)
    await db.flush()

    # Inicializa progresso para todos os alunos existentes
    res_alunos = await db.execute(
        select(Usuario)
        .join(UsuarioPerfil, UsuarioPerfil.usuario_id == Usuario.id)
        .where(UsuarioPerfil.perfil == PerfilUsuario.aluno, UsuarioPerfil.ativo == True)
    )
    status_inicial = (
        StatusProgresso.disponivel if body.prerequisito_id is None
        else StatusProgresso.bloqueado
    )
    for aluno in res_alunos.scalars().all():
        db.add(ProgressoTopico(
            usuario_id=aluno.id,
            topico_id=topico.id,
            status=status_inicial,
        ))

    await db.commit()
    await db.refresh(topico)
    # Carrega o relacionamento para evitar MissingGreenlet
    await db.execute(select(Topico).options(selectinload(Topico.materia)).where(Topico.id == topico.id))
    return topico


@router.put("/topicos/{topico_id}", response_model=TopicoOut)
async def editar_topico(
    topico_id: uuid.UUID,
    body: TopicoCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico).options(selectinload(Topico.materia)).where(Topico.id == topico_id)
    )
    topico = res.scalar_one_or_none()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")

    for k, v in body.model_dump().items():
        setattr(topico, k, v)
    await db.commit()
    await db.refresh(topico)
    return topico


@router.delete("/topicos/{topico_id}", status_code=204)
async def deletar_topico(
    topico_id: uuid.UUID,
    _:  Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Topico).where(Topico.id == topico_id))
    topico = res.scalar_one_or_none()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")
    await db.delete(topico)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# QUIZZES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/topicos/{topico_id}/quizzes", response_model=list[QuizComQuestoesOut])
async def listar_quizzes(
    topico_id: uuid.UUID,
    _:  Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Quiz)
        .options(
            selectinload(Quiz.questoes).selectinload(Questao.alternativas)
        )
        .where(Quiz.topico_id == topico_id)
        .order_by(Quiz.criado_em)
    )
    return res.scalars().all()


@router.post("/topicos/{topico_id}/quizzes", response_model=QuizOut, status_code=201)
async def criar_quiz(
    topico_id: uuid.UUID,
    body: QuizCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Topico).where(Topico.id == topico_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Tópico não encontrado")

    quiz = Quiz(topico_id=topico_id, **body.model_dump())
    db.add(quiz)
    await db.commit()
    await db.refresh(quiz)
    return quiz


@router.put("/quizzes/{quiz_id}", response_model=QuizOut)
async def editar_quiz(
    quiz_id: uuid.UUID,
    body: QuizCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    for k, v in body.model_dump().items():
        setattr(quiz, k, v)
    await db.commit()
    await db.refresh(quiz)
    return quiz


@router.delete("/quizzes/{quiz_id}", status_code=204)
async def deletar_quiz(
    quiz_id: uuid.UUID,
    _:  Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    await db.delete(quiz)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# QUESTÕES
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/quizzes/{quiz_id}/questoes", response_model=QuestaoOut, status_code=201)
async def criar_questao(
    quiz_id: uuid.UUID,
    body: QuestaoCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    # Conta ordem automaticamente
    res_ordem = await db.execute(
        select(Questao).where(Questao.quiz_id == quiz_id)
    )
    ordem = len(res_ordem.scalars().all())

    questao = Questao(quiz_id=quiz_id, ordem=ordem, **body.model_dump(exclude={"alternativas"}))
    db.add(questao)
    await db.flush()

    for i, alt in enumerate(body.alternativas):
        db.add(Alternativa(questao_id=questao.id, ordem=i, **alt.model_dump()))

    await db.commit()
    await db.refresh(questao, ["alternativas"])
    return questao


@router.put("/questoes/{questao_id}", response_model=QuestaoOut)
async def editar_questao(
    questao_id: uuid.UUID,
    body: QuestaoCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Questao)
        .options(selectinload(Questao.alternativas))
        .where(Questao.id == questao_id)
    )
    questao = res.scalar_one_or_none()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    for k, v in body.model_dump(exclude={"alternativas"}).items():
        setattr(questao, k, v)

    # Recria alternativas
    for alt in questao.alternativas:
        await db.delete(alt)
    await db.flush()
    for i, alt in enumerate(body.alternativas):
        db.add(Alternativa(questao_id=questao.id, ordem=i, **alt.model_dump()))

    await db.commit()
    await db.refresh(questao, ["alternativas"])
    return questao


@router.delete("/questoes/{questao_id}", status_code=204)
async def deletar_questao(
    questao_id: uuid.UUID,
    _:  Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Questao).where(Questao.id == questao_id))
    questao = res.scalar_one_or_none()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    await db.delete(questao)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# ANÁLISE DE RESULTADOS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/analise")
async def get_analise(
    _:  Usuario = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna dados consolidados para a aba de Análise de Resultados:
    - Métricas gerais da plataforma
    - Desempenho individual dos alunos
    - Desempenho por matéria
    - Engajamento (acesso, quiz diário, sequência)
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func, and_
    from app.models.models import TentativaQuiz, Quiz, Recomendacao

    hoje = datetime.now(timezone.utc).date()
    semana_atras = datetime.now(timezone.utc) - timedelta(days=7)
    mes_atras    = datetime.now(timezone.utc) - timedelta(days=30)

    # ── Busca todos os alunos ──────────────────────────────────────────────────
    res = await db.execute(
        select(Usuario)
        .join(UsuarioPerfil, UsuarioPerfil.usuario_id == Usuario.id)
        .where(UsuarioPerfil.perfil == PerfilUsuario.aluno, Usuario.ativo == True)
        .order_by(Usuario.nome)
    )
    alunos = res.scalars().all()
    aluno_ids = [a.id for a in alunos]

    # ── Busca todas as tentativas ──────────────────────────────────────────────
    if aluno_ids:
        res = await db.execute(
            select(TentativaQuiz)
            .options(selectinload(TentativaQuiz.quiz).selectinload(Quiz.topico).selectinload(Topico.materia))
            .where(TentativaQuiz.usuario_id.in_(aluno_ids))
            .order_by(TentativaQuiz.realizado_em)
        )
        tentativas = res.scalars().all()
    else:
        tentativas = []

    # ── Busca progressos ───────────────────────────────────────────────────────
    if aluno_ids:
        res = await db.execute(
            select(ProgressoTopico)
            .options(selectinload(ProgressoTopico.topico).selectinload(Topico.materia))
            .where(ProgressoTopico.usuario_id.in_(aluno_ids))
        )
        progressos = res.scalars().all()
    else:
        progressos = []

    # ── Agrupa tentativas por aluno e por matéria ──────────────────────────────
    from collections import defaultdict

    tent_por_aluno   = defaultdict(list)
    tent_por_materia = defaultdict(list)

    for t in tentativas:
        tent_por_aluno[t.usuario_id].append(t)
        if t.quiz and t.quiz.topico and t.quiz.topico.materia:
            mid = t.quiz.topico.materia_id
            tent_por_materia[mid].append(t)

    prog_por_aluno = defaultdict(list)
    for p in progressos:
        prog_por_aluno[p.usuario_id].append(p)

    # ── Métricas gerais ────────────────────────────────────────────────────────
    total_alunos  = len(alunos)
    def tz_aware(dt):
        """Garante que o datetime seja timezone-aware para comparação segura."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    ativos_semana = sum(
        1 for a in alunos
        if a.ultimo_acesso and tz_aware(a.ultimo_acesso) >= semana_atras
    )
    ativos_mes = sum(
        1 for a in alunos
        if a.ultimo_acesso and tz_aware(a.ultimo_acesso) >= mes_atras
    )
    quiz_hoje = sum(
        1 for a in alunos
        if a.ultimo_quiz_diario and tz_aware(a.ultimo_quiz_diario).date() == hoje
    )

    total_acertos = sum(t.acertos for t in tentativas)
    total_questoes = sum(t.total_questoes for t in tentativas)
    taxa_geral = round(total_acertos / total_questoes * 100, 1) if total_questoes else 0

    total_concluidos = sum(
        1 for p in progressos
        if p.status.value == 'concluido'
    )
    total_progresso = len(progressos)

    # ── Desempenho individual dos alunos ───────────────────────────────────────
    alunos_data = []
    for a in alunos:
        tents = tent_por_aluno[a.id]
        progs = prog_por_aluno[a.id]

        ac  = sum(t.acertos for t in tents)
        tot = sum(t.total_questoes for t in tents)
        taxa = round(ac / tot * 100, 1) if tot else None

        concluidos  = sum(1 for p in progs if p.status.value == 'concluido')
        em_progresso = sum(1 for p in progs if p.status.value == 'em_progresso')
        total_top   = len(progs)

        # Tentativas recentes (últimos 7 dias)
        tents_semana = [
            t for t in tents
            if t.realizado_em and tz_aware(t.realizado_em) >= semana_atras
        ]
        exerc_semana = len(tents_semana)

        # Dias sem acesso
        if a.ultimo_acesso:
            dias_sem_acesso = (datetime.now(timezone.utc) - tz_aware(a.ultimo_acesso)).days
        else:
            dias_sem_acesso = None

        # Classificação de risco
        if dias_sem_acesso is None or dias_sem_acesso > 14:
            risco = 'alto'
        elif dias_sem_acesso > 7:
            risco = 'medio'
        else:
            risco = 'baixo'

        # Histórico de evolução — uma entrada por tentativa, ordenada por data
        historico = []
        tents_ord = sorted(tents, key=lambda t: t.realizado_em or datetime.min)
        for idx_t, t in enumerate(tents_ord):
            taxa_t = round(t.acertos / t.total_questoes * 100, 1) if t.total_questoes else 0
            # Variação em relação à tentativa anterior
            variacao = None
            if idx_t > 0:
                ant = tents_ord[idx_t - 1]
                taxa_ant = round(ant.acertos / ant.total_questoes * 100, 1) if ant.total_questoes else 0
                variacao = round(taxa_t - taxa_ant, 1)
            materia_nome = (
                t.quiz.topico.materia.nome
                if t.quiz and t.quiz.topico and t.quiz.topico.materia
                else 'Geral'
            )
            quiz_nome = t.quiz.titulo if t.quiz else '—'
            historico.append({
                'data':        t.realizado_em.strftime('%d/%m') if t.realizado_em else '—',
                'data_iso':    t.realizado_em.isoformat() if t.realizado_em else None,
                'acertos':     t.acertos,
                'total':       t.total_questoes,
                'taxa':        taxa_t,
                'variacao':    variacao,
                'materia':     materia_nome,
                'quiz':        quiz_nome,
            })

        # Tendência geral: compara média das últimas 3 com as primeiras 3 tentativas
        tendencia = None
        if len(historico) >= 4:
            inicio = sum(h['taxa'] for h in historico[:3]) / 3
            fim    = sum(h['taxa'] for h in historico[-3:]) / 3
            diff   = round(fim - inicio, 1)
            tendencia = {'diff': diff, 'sentido': 'melhora' if diff > 0 else 'piora' if diff < 0 else 'estavel'}

        alunos_data.append({
            'id':             str(a.id),
            'nome':           a.nome,
            'email':          a.email,
            'taxa_acerto':    taxa,
            'total_exercicios': tot,
            'exerc_semana':   exerc_semana,
            'topicos_concluidos': concluidos,
            'topicos_em_progresso': em_progresso,
            'total_topicos':  total_top,
            'ultimo_acesso':  a.ultimo_acesso.isoformat() if a.ultimo_acesso else None,
            'dias_sem_acesso': dias_sem_acesso,
            'quiz_diario_hoje': bool(a.ultimo_quiz_diario and tz_aware(a.ultimo_quiz_diario).date() == hoje),
            'risco':          risco,
            'historico':      historico,
            'tendencia':      tendencia,
        })

    # ── Desempenho por matéria ─────────────────────────────────────────────────
    res_materias = await db.execute(
        select(Materia).where(Materia.ativo == True).order_by(Materia.ordem)
    )
    todas_materias = res_materias.scalars().all()

    materias_data = []
    for m in todas_materias:
        tents = tent_por_materia.get(m.id, [])
        ac  = sum(t.acertos for t in tents)
        tot = sum(t.total_questoes for t in tents)
        taxa = round(ac / tot * 100, 1) if tot else None

        # Alunos com progresso nessa matéria
        progs_mat = [
            p for p in progressos
            if p.topico and p.topico.materia_id == m.id
        ]
        alunos_mat = len(set(p.usuario_id for p in progs_mat))
        concluidos_mat = sum(1 for p in progs_mat if p.status.value == 'concluido')
        total_progs_mat = len(progs_mat)

        materias_data.append({
            'id':           str(m.id),
            'nome':         m.nome,
            'icone':        m.icone or '📚',
            'cor':          m.cor or '#3b82f6',
            'taxa_acerto':  taxa,
            'total_tentativas': len(tents),
            'alunos_ativos': alunos_mat,
            'topicos_concluidos': concluidos_mat,
            'total_progresso': total_progs_mat,
        })

    return {
        'geral': {
            'total_alunos':    total_alunos,
            'ativos_semana':   ativos_semana,
            'ativos_mes':      ativos_mes,
            'quiz_diario_hoje': quiz_hoje,
            'taxa_acerto_geral': taxa_geral,
            'total_exercicios': len(tentativas),
            'topicos_concluidos': total_concluidos,
            'total_progresso':  total_progresso,
        },
        'alunos':   alunos_data,
        'materias': materias_data,
    }
