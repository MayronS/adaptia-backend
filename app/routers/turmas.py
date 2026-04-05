import uuid, random
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    Turma, TurmaAluno, TurmaQuiz, TurmaQuestao, TurmaAlternativa,
    TentativaTurmaQuiz, TurmaRespostaQuestao,
    VinculoProfessorAluno, StatusVinculo,
    Usuario, UsuarioPerfil, PerfilUsuario,
)
from app.schemas.schemas import (
    TurmaCreate, TurmaOut, TurmaQuizCreate, TurmaQuizOut,
    TurmaQuestaoCreate, TurmaQuestaoOut,
    TentativaTurmaCreate, TentativaTurmaOut,
    TurmaAlternativaOut,
)
from app.services.auth_service import require_professor, require_aluno

router = APIRouter(prefix="/turmas", tags=["turmas"])


# ── helpers ───────────────────────────────────────────────────────────────────

async def _get_turma_do_professor(turma_id: uuid.UUID, professor_id: uuid.UUID, db: AsyncSession) -> Turma:
    res = await db.execute(
        select(Turma)
        .options(
            selectinload(Turma.professor).selectinload(Usuario.perfis),
            selectinload(Turma.alunos).selectinload(TurmaAluno.aluno).selectinload(Usuario.perfis),
            selectinload(Turma.quizzes).selectinload(TurmaQuiz.questoes).selectinload(TurmaQuestao.alternativas),
        )
        .where(Turma.id == turma_id, Turma.professor_id == professor_id)
    )
    turma = res.scalar_one_or_none()
    if not turma:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    return turma


# ══════════════════════════════════════════════════════════════════════════════
# TURMAS — PROFESSOR
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/professor", response_model=list[TurmaOut])
async def listar_turmas_professor(
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Turma)
        .options(
            selectinload(Turma.professor).selectinload(Usuario.perfis),
            selectinload(Turma.alunos).selectinload(TurmaAluno.aluno).selectinload(Usuario.perfis),
            selectinload(Turma.quizzes).selectinload(TurmaQuiz.questoes).selectinload(TurmaQuestao.alternativas),
        )
        .where(Turma.professor_id == user.id, Turma.ativo == True)
        .order_by(Turma.criado_em.desc())
    )
    return res.scalars().all()


@router.post("/professor", response_model=TurmaOut, status_code=201)
async def criar_turma(
    body: TurmaCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    turma = Turma(professor_id=user.id, nome=body.nome, descricao=body.descricao)
    db.add(turma)
    await db.commit()
    res = await db.execute(
        select(Turma)
        .options(
            selectinload(Turma.professor).selectinload(Usuario.perfis),
            selectinload(Turma.alunos).selectinload(TurmaAluno.aluno).selectinload(Usuario.perfis),
            selectinload(Turma.quizzes).selectinload(TurmaQuiz.questoes).selectinload(TurmaQuestao.alternativas),
        )
        .where(Turma.id == turma.id)
    )
    return res.scalar_one()


@router.put("/professor/{turma_id}", response_model=TurmaOut)
async def editar_turma(
    turma_id: uuid.UUID,
    body: TurmaCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    turma = await _get_turma_do_professor(turma_id, user.id, db)
    turma.nome = body.nome
    turma.descricao = body.descricao
    await db.commit()
    return await _get_turma_do_professor(turma_id, user.id, db)


@router.delete("/professor/{turma_id}", status_code=204)
async def deletar_turma(
    turma_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    turma = await _get_turma_do_professor(turma_id, user.id, db)
    await db.delete(turma)
    await db.commit()


# ── Alunos da turma ───────────────────────────────────────────────────────────

@router.post("/professor/{turma_id}/alunos/{aluno_id}", status_code=201)
async def adicionar_aluno_turma(
    turma_id: uuid.UUID,
    aluno_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    """Adiciona aluno à turma — exige vínculo aceito entre professor e aluno."""
    await _get_turma_do_professor(turma_id, user.id, db)

    # Verifica vínculo aceito
    res_v = await db.execute(
        select(VinculoProfessorAluno).where(
            VinculoProfessorAluno.professor_id == user.id,
            VinculoProfessorAluno.aluno_id     == aluno_id,
            VinculoProfessorAluno.status       == StatusVinculo.aceito,
        )
    )
    if not res_v.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Este aluno não está vinculado a você")

    # Verifica se já está na turma
    res_ta = await db.execute(
        select(TurmaAluno).where(TurmaAluno.turma_id == turma_id, TurmaAluno.aluno_id == aluno_id)
    )
    if res_ta.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Aluno já está nesta turma")

    db.add(TurmaAluno(turma_id=turma_id, aluno_id=aluno_id))
    await db.commit()
    return {"ok": True}


@router.delete("/professor/{turma_id}/alunos/{aluno_id}", status_code=204)
async def remover_aluno_turma(
    turma_id: uuid.UUID,
    aluno_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    await _get_turma_do_professor(turma_id, user.id, db)
    res = await db.execute(
        select(TurmaAluno).where(TurmaAluno.turma_id == turma_id, TurmaAluno.aluno_id == aluno_id)
    )
    ta = res.scalar_one_or_none()
    if not ta:
        raise HTTPException(status_code=404, detail="Aluno não encontrado nesta turma")
    await db.delete(ta)
    await db.commit()


# ── Quizzes da turma ──────────────────────────────────────────────────────────

@router.post("/professor/{turma_id}/quizzes", response_model=TurmaQuizOut, status_code=201)
async def criar_quiz_turma(
    turma_id: uuid.UUID,
    body: TurmaQuizCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    await _get_turma_do_professor(turma_id, user.id, db)
    quiz = TurmaQuiz(turma_id=turma_id, **body.model_dump())
    db.add(quiz)
    await db.commit()
    res = await db.execute(
        select(TurmaQuiz)
        .options(selectinload(TurmaQuiz.questoes).selectinload(TurmaQuestao.alternativas))
        .where(TurmaQuiz.id == quiz.id)
    )
    return res.scalar_one()


@router.put("/professor/quizzes/{quiz_id}", response_model=TurmaQuizOut)
async def editar_quiz_turma(
    quiz_id: uuid.UUID,
    body: TurmaQuizCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(TurmaQuiz)
        .join(Turma, Turma.id == TurmaQuiz.turma_id)
        .options(selectinload(TurmaQuiz.questoes).selectinload(TurmaQuestao.alternativas))
        .where(TurmaQuiz.id == quiz_id, Turma.professor_id == user.id)
    )
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    for k, v in body.model_dump().items():
        setattr(quiz, k, v)
    await db.commit()
    await db.refresh(quiz, ["questoes"])
    return quiz


@router.delete("/professor/quizzes/{quiz_id}", status_code=204)
async def deletar_quiz_turma(
    quiz_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(TurmaQuiz)
        .join(Turma, Turma.id == TurmaQuiz.turma_id)
        .where(TurmaQuiz.id == quiz_id, Turma.professor_id == user.id)
    )
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    await db.delete(quiz)
    await db.commit()


# ── Questões do quiz de turma ─────────────────────────────────────────────────

@router.post("/professor/quizzes/{quiz_id}/questoes", response_model=TurmaQuestaoOut, status_code=201)
async def criar_questao_turma(
    quiz_id: uuid.UUID,
    body: TurmaQuestaoCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(TurmaQuiz)
        .join(Turma, Turma.id == TurmaQuiz.turma_id)
        .where(TurmaQuiz.id == quiz_id, Turma.professor_id == user.id)
    )
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    res_ord = await db.execute(select(TurmaQuestao).where(TurmaQuestao.quiz_id == quiz_id))
    ordem = len(res_ord.scalars().all())

    questao = TurmaQuestao(quiz_id=quiz_id, ordem=ordem, **body.model_dump(exclude={"alternativas"}))
    db.add(questao)
    await db.flush()

    for i, alt in enumerate(body.alternativas):
        db.add(TurmaAlternativa(questao_id=questao.id, ordem=i, **alt.model_dump()))

    await db.commit()
    await db.refresh(questao, ["alternativas"])
    return questao


@router.put("/professor/questoes/{questao_id}", response_model=TurmaQuestaoOut)
async def editar_questao_turma(
    questao_id: uuid.UUID,
    body: TurmaQuestaoCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(TurmaQuestao)
        .options(selectinload(TurmaQuestao.alternativas))
        .join(TurmaQuiz, TurmaQuiz.id == TurmaQuestao.quiz_id)
        .join(Turma, Turma.id == TurmaQuiz.turma_id)
        .where(TurmaQuestao.id == questao_id, Turma.professor_id == user.id)
    )
    questao = res.scalar_one_or_none()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    for k, v in body.model_dump(exclude={"alternativas"}).items():
        setattr(questao, k, v)
    for alt in questao.alternativas:
        await db.delete(alt)
    await db.flush()
    for i, alt in enumerate(body.alternativas):
        db.add(TurmaAlternativa(questao_id=questao.id, ordem=i, **alt.model_dump()))

    await db.commit()
    await db.refresh(questao, ["alternativas"])
    return questao


@router.delete("/professor/questoes/{questao_id}", status_code=204)
async def deletar_questao_turma(
    questao_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(TurmaQuestao)
        .join(TurmaQuiz, TurmaQuiz.id == TurmaQuestao.quiz_id)
        .join(Turma, Turma.id == TurmaQuiz.turma_id)
        .where(TurmaQuestao.id == questao_id, Turma.professor_id == user.id)
    )
    questao = res.scalar_one_or_none()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    await db.delete(questao)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# TURMAS — ALUNO
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/aluno", response_model=list[TurmaOut])
async def listar_turmas_aluno(
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Retorna todas as turmas em que o aluno está matriculado."""
    res = await db.execute(
        select(Turma)
        .join(TurmaAluno, TurmaAluno.turma_id == Turma.id)
        .options(
            selectinload(Turma.professor).selectinload(Usuario.perfis),
            selectinload(Turma.alunos).selectinload(TurmaAluno.aluno).selectinload(Usuario.perfis),
            selectinload(Turma.quizzes).selectinload(TurmaQuiz.questoes).selectinload(TurmaQuestao.alternativas),
        )
        .where(TurmaAluno.aluno_id == user.id, Turma.ativo == True)
        .order_by(Turma.criado_em.desc())
    )
    return res.scalars().all()


@router.get("/aluno/{turma_id}", response_model=TurmaOut)
async def detalhe_turma_aluno(
    turma_id: uuid.UUID,
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    res_ta = await db.execute(
        select(TurmaAluno).where(TurmaAluno.turma_id == turma_id, TurmaAluno.aluno_id == user.id)
    )
    if not res_ta.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Você não está nesta turma")

    res = await db.execute(
        select(Turma)
        .options(
            selectinload(Turma.professor).selectinload(Usuario.perfis),
            selectinload(Turma.alunos).selectinload(TurmaAluno.aluno).selectinload(Usuario.perfis),
            selectinload(Turma.quizzes).selectinload(TurmaQuiz.questoes).selectinload(TurmaQuestao.alternativas),
        )
        .where(Turma.id == turma_id)
    )
    return res.scalar_one()


@router.post("/aluno/tentativas", response_model=TentativaTurmaOut, status_code=201)
async def submeter_tentativa_turma(
    body: TentativaTurmaCreate,
    user: Usuario = Depends(require_aluno),
    db:   AsyncSession = Depends(get_db),
):
    """Aluno submete respostas de um quiz de turma."""
    res_q = await db.execute(
        select(TurmaQuiz)
        .options(selectinload(TurmaQuiz.questoes).selectinload(TurmaQuestao.alternativas))
        .where(TurmaQuiz.id == body.quiz_id, TurmaQuiz.ativo == True)
    )
    quiz = res_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    # Verifica se aluno está na turma
    res_ta = await db.execute(
        select(TurmaAluno).where(TurmaAluno.turma_id == quiz.turma_id, TurmaAluno.aluno_id == user.id)
    )
    if not res_ta.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Você não está nesta turma")

    questoes_map = {q.id: q for q in quiz.questoes}
    acertos = 0

    tentativa = TentativaTurmaQuiz(
        quiz_id=body.quiz_id,
        aluno_id=user.id,
        total_questoes=len(body.respostas),
        tempo_gasto_seg=body.tempo_gasto_seg,
    )
    db.add(tentativa)
    await db.flush()

    for r in body.respostas:
        questao = questoes_map.get(r.questao_id)
        correta = False
        if questao and r.alternativa_id:
            alt = next((a for a in questao.alternativas if a.id == r.alternativa_id), None)
            correta = bool(alt and alt.correta)
        if correta:
            acertos += 1
        db.add(TurmaRespostaQuestao(
            tentativa_id=tentativa.id,
            questao_id=r.questao_id,
            alternativa_id=r.alternativa_id,
            correta=correta,
        ))

    pontuacao = round(acertos / max(len(body.respostas), 1) * 100)
    tentativa.acertos   = acertos
    tentativa.pontuacao = pontuacao

    await db.commit()
    await db.refresh(tentativa)
    return tentativa
