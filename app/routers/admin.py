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
    return topico


@router.put("/topicos/{topico_id}", response_model=TopicoOut)
async def editar_topico(
    topico_id: uuid.UUID,
    body: TopicoCreate,
    _:    Usuario = Depends(require_admin),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Topico).where(Topico.id == topico_id))
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
