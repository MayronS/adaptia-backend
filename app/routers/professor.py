import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    Usuario, UsuarioPerfil, PerfilUsuario,
    TentativaQuiz, ProgressoTopico, Materia, Topico, Quiz, Questao, Alternativa,
    VinculoProfessorAluno, StatusVinculo,
)
from app.schemas.schemas import (
    DashboardProfessorOut, AlunoResumoOut, UsuarioOut,
    MateriaOut, MateriaCreate, TopicoOut, TopicoCreate, QuizOut, QuizCreate, QuizComQuestoesOut,
    QuestaoOut, QuestaoCreate, AlternativaOut, AlternativaCreate,
    ConviteCreate, ConviteOut, ResponderConviteRequest,
)
from app.services.auth_service import require_professor, get_current_user

router = APIRouter(prefix="/professor", tags=["professor"])


# ── helpers ───────────────────────────────────────────────────────────────────

async def _resumo_aluno(aluno: Usuario, db: AsyncSession) -> AlunoResumoOut:
    res_tent = await db.execute(
        select(TentativaQuiz).where(TentativaQuiz.usuario_id == aluno.id)
    )
    tentativas = res_tent.scalars().all()
    total_q = sum(t.total_questoes for t in tentativas)
    acertos = sum(t.acertos for t in tentativas)
    media   = round(sum(t.pontuacao for t in tentativas) / max(len(tentativas), 1), 1)
    taxa    = round(acertos / max(total_q, 1) * 100, 1)
    return AlunoResumoOut(
        usuario=UsuarioOut.from_usuario(aluno),
        pontuacao_media=media,
        taxa_acerto_pct=taxa,
        total_tentativas=len(tentativas),
        ultimo_acesso=aluno.ultimo_acesso,
    )


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — só alunos vinculados e aceitos
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard", response_model=DashboardProfessorOut)
async def dashboard(
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    # Busca apenas alunos com vínculo aceito por este professor
    res = await db.execute(
        select(Usuario)
        .join(VinculoProfessorAluno, VinculoProfessorAluno.aluno_id == Usuario.id)
        .options(selectinload(Usuario.perfis))
        .where(
            VinculoProfessorAluno.professor_id == user.id,
            VinculoProfessorAluno.status       == StatusVinculo.aceito,
            Usuario.ativo == True,
        )
    )
    alunos = res.scalars().all()

    resumos: list[AlunoResumoOut] = []
    precisam_apoio = 0
    for aluno in alunos:
        r = await _resumo_aluno(aluno, db)
        if r.pontuacao_media < 50 or r.taxa_acerto_pct < 40:
            precisam_apoio += 1
        resumos.append(r)

    media_turma = round(
        sum(r.pontuacao_media for r in resumos) / max(len(resumos), 1), 1
    )
    sete_dias = datetime.now(timezone.utc) - timedelta(days=7)
    alunos_ativos = sum(
        1 for r in resumos
        if r.ultimo_acesso and r.ultimo_acesso >= sete_dias
    )

    return DashboardProfessorOut(
        usuario=UsuarioOut.from_usuario(user),
        media_turma=media_turma,
        total_alunos=len(alunos),
        alunos_ativos=alunos_ativos,
        precisam_apoio=precisam_apoio,
        alunos=sorted(resumos, key=lambda x: x.pontuacao_media, reverse=True),
    )


# ── Detalhe de aluno ──────────────────────────────────────────────────────────

@router.get("/alunos/{aluno_id}/progresso")
async def progresso_aluno(
    aluno_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    await _check_vinculo(user.id, aluno_id, db)
    res = await db.execute(
        select(ProgressoTopico)
        .options(selectinload(ProgressoTopico.topico))
        .where(ProgressoTopico.usuario_id == aluno_id)
    )
    return [
        {
            "topico": p.topico.titulo, "status": p.status,
            "pontuacao": p.pontuacao, "iniciado_em": p.iniciado_em, "concluido_em": p.concluido_em,
        }
        for p in res.scalars().all()
    ]


@router.get("/alunos/{aluno_id}/tentativas")
async def tentativas_aluno(
    aluno_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    await _check_vinculo(user.id, aluno_id, db)
    res = await db.execute(
        select(TentativaQuiz)
        .options(selectinload(TentativaQuiz.quiz))
        .where(TentativaQuiz.usuario_id == aluno_id)
        .order_by(TentativaQuiz.realizado_em.desc())
        .limit(30)
    )
    return [
        {
            "quiz": t.quiz.titulo, "pontuacao": t.pontuacao,
            "acertos": t.acertos, "total_questoes": t.total_questoes,
            "taxa_acerto_pct": round(t.acertos / max(t.total_questoes, 1) * 100, 1),
            "tempo_gasto_seg": t.tempo_gasto_seg, "realizado_em": t.realizado_em,
        }
        for t in res.scalars().all()
    ]


async def _check_vinculo(professor_id, aluno_id, db):
    res = await db.execute(
        select(VinculoProfessorAluno).where(
            VinculoProfessorAluno.professor_id == professor_id,
            VinculoProfessorAluno.aluno_id     == aluno_id,
            VinculoProfessorAluno.status       == StatusVinculo.aceito,
        )
    )
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Sem vínculo aceito com este aluno")


# ── Conteúdo (leitura) ────────────────────────────────────────────────────────

@router.get("/materias", response_model=list[MateriaOut])
async def listar_materias(
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    """Lista TODAS as matérias ativas (admin + professor). Professor pode visualizar todas."""
    res = await db.execute(
        select(Materia)
        .options(selectinload(Materia.criado_por))
        .where(Materia.ativo == True)
        .order_by(Materia.ordem, Materia.nome)
    )
    return [MateriaOut.from_orm_with_autor(m) for m in res.scalars().all()]


@router.get("/materias/{materia_id}/topicos", response_model=list[TopicoOut])
async def listar_topicos(
    materia_id: uuid.UUID,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico)
        .options(selectinload(Topico.materia))
        .where(Topico.materia_id == materia_id, Topico.ativo == True)
        .order_by(Topico.ordem)
    )
    return res.scalars().all()


@router.get("/topicos/{topico_id}/quizzes", response_model=list[QuizComQuestoesOut])
async def listar_quizzes(
    topico_id: uuid.UUID,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Quiz)
        .options(selectinload(Quiz.questoes).selectinload(Questao.alternativas))
        .where(Quiz.topico_id == topico_id)
        .order_by(Quiz.criado_em)
    )
    return res.scalars().all()


# ══════════════════════════════════════════════════════════════════════════════
# MATÉRIAS DO PROFESSOR — CRUD (somente matérias criadas pelo próprio professor)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/materias", response_model=MateriaOut, status_code=201)
async def criar_materia(
    body: MateriaCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    existe = await db.execute(select(Materia).where(Materia.nome == body.nome))
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Já existe uma matéria com esse nome")

    dados = body.model_dump()
    materia = Materia(**dados, criado_por_id=user.id)
    db.add(materia)
    await db.commit()
    await db.refresh(materia)
    # Carrega relação criado_por
    res = await db.execute(
        select(Materia).options(selectinload(Materia.criado_por)).where(Materia.id == materia.id)
    )
    return MateriaOut.from_orm_with_autor(res.scalar_one())


@router.put("/materias/{materia_id}", response_model=MateriaOut)
async def editar_materia(
    materia_id: uuid.UUID,
    body: MateriaCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Materia).options(selectinload(Materia.criado_por)).where(Materia.id == materia_id)
    )
    materia = res.scalar_one_or_none()
    if not materia:
        raise HTTPException(status_code=404, detail="Matéria não encontrada")
    if materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode editar matérias que criou")

    for k, v in body.model_dump().items():
        setattr(materia, k, v)
    await db.commit()
    await db.refresh(materia)
    res2 = await db.execute(
        select(Materia).options(selectinload(Materia.criado_por)).where(Materia.id == materia.id)
    )
    return MateriaOut.from_orm_with_autor(res2.scalar_one())


@router.delete("/materias/{materia_id}", status_code=204)
async def deletar_materia(
    materia_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.id == materia_id))
    materia = res.scalar_one_or_none()
    if not materia:
        raise HTTPException(status_code=404, detail="Matéria não encontrada")
    if materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode excluir matérias que criou")
    await db.delete(materia)
    await db.commit()


# ── Tópicos das matérias do professor (CRUD) ──────────────────────────────────

@router.post("/materias/{materia_id}/topicos", response_model=TopicoOut, status_code=201)
async def criar_topico_prof(
    materia_id: uuid.UUID,
    body: TopicoCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.id == materia_id))
    materia = res.scalar_one_or_none()
    if not materia:
        raise HTTPException(status_code=404, detail="Matéria não encontrada")
    if materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode adicionar tópicos em matérias que criou")

    topico = Topico(materia_id=materia_id, **body.model_dump())
    db.add(topico)
    await db.commit()
    await db.refresh(topico)
    res2 = await db.execute(
        select(Topico).options(selectinload(Topico.materia)).where(Topico.id == topico.id)
    )
    return res2.scalar_one()


@router.put("/topicos/{topico_id}", response_model=TopicoOut)
async def editar_topico_prof(
    topico_id: uuid.UUID,
    body: TopicoCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico).options(selectinload(Topico.materia)).where(Topico.id == topico_id)
    )
    topico = res.scalar_one_or_none()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")
    if not topico.materia or topico.materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode editar tópicos de matérias que criou")

    for k, v in body.model_dump().items():
        setattr(topico, k, v)
    await db.commit()
    await db.refresh(topico)
    res2 = await db.execute(
        select(Topico).options(selectinload(Topico.materia)).where(Topico.id == topico.id)
    )
    return res2.scalar_one()


@router.delete("/topicos/{topico_id}", status_code=204)
async def deletar_topico_prof(
    topico_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico).options(selectinload(Topico.materia)).where(Topico.id == topico_id)
    )
    topico = res.scalar_one_or_none()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")
    if not topico.materia or topico.materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode excluir tópicos de matérias que criou")
    await db.delete(topico)
    await db.commit()


# ── Quizzes (CRUD) ─────────────────────────────────────────────────────────────

@router.post("/topicos/{topico_id}/quizzes", response_model=QuizOut, status_code=201)
async def criar_quiz_prof(
    topico_id: uuid.UUID,
    body: QuizCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico).options(selectinload(Topico.materia)).where(Topico.id == topico_id)
    )
    topico = res.scalar_one_or_none()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")
    if not topico.materia or topico.materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode criar quizzes em matérias que criou")

    quiz = Quiz(topico_id=topico_id, **body.model_dump())
    db.add(quiz)
    await db.commit()
    await db.refresh(quiz)
    return quiz


@router.put("/quizzes/{quiz_id}", response_model=QuizOut)
async def editar_quiz_prof(
    quiz_id: uuid.UUID,
    body: QuizCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Quiz)
        .options(selectinload(Quiz.topico).selectinload(Topico.materia))
        .where(Quiz.id == quiz_id)
    )
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if not quiz.topico.materia or quiz.topico.materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode editar quizzes de matérias que criou")

    for k, v in body.model_dump().items():
        setattr(quiz, k, v)
    await db.commit()
    await db.refresh(quiz)
    return quiz


@router.delete("/quizzes/{quiz_id}", status_code=204)
async def deletar_quiz_prof(
    quiz_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Quiz)
        .options(selectinload(Quiz.topico).selectinload(Topico.materia))
        .where(Quiz.id == quiz_id)
    )
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if not quiz.topico.materia or quiz.topico.materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode excluir quizzes de matérias que criou")
    await db.delete(quiz)
    await db.commit()


# ── Questões (CRUD) ────────────────────────────────────────────────────────────

@router.post("/quizzes/{quiz_id}/questoes", response_model=QuestaoOut, status_code=201)
async def criar_questao_prof(
    quiz_id: uuid.UUID,
    body: QuestaoCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Quiz)
        .options(selectinload(Quiz.topico).selectinload(Topico.materia))
        .where(Quiz.id == quiz_id)
    )
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if not quiz.topico.materia or quiz.topico.materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode criar questões em matérias que criou")

    res_ordem = await db.execute(select(Questao).where(Questao.quiz_id == quiz_id))
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
async def editar_questao_prof(
    questao_id: uuid.UUID,
    body: QuestaoCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Questao)
        .options(
            selectinload(Questao.alternativas),
            selectinload(Questao.quiz).selectinload(Quiz.topico).selectinload(Topico.materia),
        )
        .where(Questao.id == questao_id)
    )
    questao = res.scalar_one_or_none()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    if not questao.quiz.topico.materia or questao.quiz.topico.materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode editar questões de matérias que criou")

    for k, v in body.model_dump(exclude={"alternativas"}).items():
        setattr(questao, k, v)

    for alt in questao.alternativas:
        await db.delete(alt)
    await db.flush()
    for i, alt in enumerate(body.alternativas):
        db.add(Alternativa(questao_id=questao.id, ordem=i, **alt.model_dump()))

    await db.commit()
    await db.refresh(questao, ["alternativas"])
    return questao


@router.delete("/questoes/{questao_id}", status_code=204)
async def deletar_questao_prof(
    questao_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Questao)
        .options(selectinload(Questao.quiz).selectinload(Quiz.topico).selectinload(Topico.materia))
        .where(Questao.id == questao_id)
    )
    questao = res.scalar_one_or_none()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    if not questao.quiz.topico.materia or questao.quiz.topico.materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Você só pode excluir questões de matérias que criou")
    await db.delete(questao)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# CONVITES
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/alunos-vinculados", response_model=list[UsuarioOut])
async def listar_alunos_vinculados(
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    """Retorna todos os alunos com vínculo aceito com este professor."""
    res = await db.execute(
        select(Usuario)
        .join(VinculoProfessorAluno, VinculoProfessorAluno.aluno_id == Usuario.id)
        .options(selectinload(Usuario.perfis))
        .where(
            VinculoProfessorAluno.professor_id == user.id,
            VinculoProfessorAluno.status       == StatusVinculo.aceito,
            Usuario.ativo == True,
        )
        .order_by(Usuario.nome)
    )
    alunos = res.scalars().all()
    return [UsuarioOut.from_usuario(a) for a in alunos]

@router.post("/convites", response_model=ConviteOut, status_code=201)
async def enviar_convite(
    body: ConviteCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    """Professor envia convite de orientação para um aluno pelo e-mail."""
    # Busca o aluno pelo e-mail
    res = await db.execute(
        select(Usuario)
        .options(selectinload(Usuario.perfis))
        .where(Usuario.email == body.aluno_email, Usuario.ativo == True)
    )
    aluno = res.scalar_one_or_none()

    if not aluno:
        raise HTTPException(status_code=404, detail="Nenhum usuário encontrado com esse e-mail")

    if not aluno.tem_perfil(PerfilUsuario.aluno):
        raise HTTPException(status_code=400, detail="Este usuário não possui perfil de aluno")

    if aluno.id == user.id:
        raise HTTPException(status_code=400, detail="Você não pode se convidar")

    # Verifica se já existe vínculo
    res_v = await db.execute(
        select(VinculoProfessorAluno).where(
            VinculoProfessorAluno.professor_id == user.id,
            VinculoProfessorAluno.aluno_id     == aluno.id,
        )
    )
    existente = res_v.scalar_one_or_none()
    if existente:
        if existente.status == StatusVinculo.aceito:
            raise HTTPException(status_code=409, detail="Este aluno já está na sua turma")
        if existente.status == StatusVinculo.pendente:
            raise HTTPException(status_code=409, detail="Convite já enviado, aguardando resposta do aluno")
        # recusado → permite reenviar
        existente.status = StatusVinculo.pendente
        existente.criado_em = datetime.now(timezone.utc)
        existente.respondido_em = None
        await db.commit()
        # Recarrega com relações para serialização correta
        res_re = await db.execute(
            select(VinculoProfessorAluno)
            .options(selectinload(VinculoProfessorAluno.professor).selectinload(Usuario.perfis),
                     selectinload(VinculoProfessorAluno.aluno).selectinload(Usuario.perfis))
            .where(VinculoProfessorAluno.id == existente.id)
        )
        return res_re.scalar_one()

    vinculo = VinculoProfessorAluno(professor_id=user.id, aluno_id=aluno.id)
    db.add(vinculo)
    await db.commit()
    await db.refresh(vinculo)

    res_full = await db.execute(
        select(VinculoProfessorAluno)
        .options(selectinload(VinculoProfessorAluno.professor).selectinload(Usuario.perfis),
                 selectinload(VinculoProfessorAluno.aluno).selectinload(Usuario.perfis))
        .where(VinculoProfessorAluno.id == vinculo.id)
    )
    return res_full.scalar_one()


@router.get("/convites", response_model=list[ConviteOut])
async def listar_convites_enviados(
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    """Lista todos os convites enviados pelo professor."""
    res = await db.execute(
        select(VinculoProfessorAluno)
        .options(selectinload(VinculoProfessorAluno.aluno).selectinload(Usuario.perfis))
        .where(VinculoProfessorAluno.professor_id == user.id)
        .order_by(VinculoProfessorAluno.criado_em.desc())
    )
    return res.scalars().all()


@router.delete("/convites/{vinculo_id}", status_code=204)
async def cancelar_convite(
    vinculo_id: uuid.UUID,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    """Professor cancela convite pendente ou remove vínculo aceito."""
    res = await db.execute(
        select(VinculoProfessorAluno).where(
            VinculoProfessorAluno.id           == vinculo_id,
            VinculoProfessorAluno.professor_id == user.id,
        )
    )
    vinculo = res.scalar_one_or_none()
    if not vinculo:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado")
    await db.delete(vinculo)
    await db.commit()