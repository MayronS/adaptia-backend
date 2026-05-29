import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    Usuario, UsuarioPerfil, PerfilUsuario,
    TentativaQuiz, ProgressoTopico, Materia, Topico, Quiz, Questao, Alternativa,
    VinculoProfessorAluno, StatusVinculo,
)
from app.schemas.schemas import (
    DashboardProfessorOut, AlunoResumoOut, UsuarioOut,
    MateriaOut, MateriaCreate, TopicoOut, TopicoCreate,
    QuizOut, QuizComQuestoesOut, QuizCreate, QuestaoOut, QuestaoCreate,
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
        if r.pontuacao_media < 60 or r.taxa_acerto_pct < 40:
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


# ── Conteúdo ──────────────────────────────────────────────────────────────────

@router.get("/materias", response_model=list[MateriaOut])
async def listar_materias(
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.ativo == True).order_by(Materia.ordem))
    return res.scalars().all()


@router.post("/materias", response_model=MateriaOut, status_code=201)
async def criar_materia(
    body: MateriaCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    materia = Materia(**body.model_dump(), criado_por_id=user.id)
    db.add(materia)
    await db.commit()
    await db.refresh(materia)
    return materia


@router.put("/materias/{materia_id}", response_model=MateriaOut)
async def editar_materia(
    materia_id: uuid.UUID,
    body: MateriaCreate,
    user: Usuario = Depends(require_professor),
    db:   AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.id == materia_id))
    materia = res.scalar_one_or_none()
    if not materia:
        raise HTTPException(status_code=404, detail="Matéria não encontrada")
    if materia.criado_por_id and materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Sem permissão para editar esta matéria")
    for k, v in body.model_dump().items():
        setattr(materia, k, v)
    await db.commit()
    await db.refresh(materia)
    return materia


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
    if materia.criado_por_id and materia.criado_por_id != user.id:
        raise HTTPException(status_code=403, detail="Sem permissão para excluir esta matéria")
    await db.delete(materia)
    await db.commit()


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


@router.post("/materias/{materia_id}/topicos", response_model=TopicoOut, status_code=201)
async def criar_topico(
    materia_id: uuid.UUID,
    body: TopicoCreate,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.id == materia_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Matéria não encontrada")
    topico = Topico(**body.model_dump(), materia_id=materia_id)
    db.add(topico)
    await db.commit()
    res2 = await db.execute(
        select(Topico).options(selectinload(Topico.materia)).where(Topico.id == topico.id)
    )
    return res2.scalar_one()


@router.put("/materias/{materia_id}/topicos/{topico_id}", response_model=TopicoOut)
async def editar_topico(
    materia_id: uuid.UUID,
    topico_id:  uuid.UUID,
    body: TopicoCreate,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico).options(selectinload(Topico.materia))
        .where(Topico.id == topico_id, Topico.materia_id == materia_id)
    )
    topico = res.scalar_one_or_none()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")
    for k, v in body.model_dump().items():
        setattr(topico, k, v)
    await db.commit()
    await db.refresh(topico)
    return topico


@router.delete("/materias/{materia_id}/topicos/{topico_id}", status_code=204)
async def deletar_topico(
    materia_id: uuid.UUID,
    topico_id:  uuid.UUID,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico).where(Topico.id == topico_id, Topico.materia_id == materia_id)
    )
    topico = res.scalar_one_or_none()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")
    await db.delete(topico)
    await db.commit()


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


@router.post("/topicos/{topico_id}/quizzes", response_model=QuizOut, status_code=201)
async def criar_quiz(
    topico_id: uuid.UUID,
    body: QuizCreate,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
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
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
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
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = res.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    await db.delete(quiz)
    await db.commit()


# ── Questões ──────────────────────────────────────────────────────────────────

@router.post("/quizzes/{quiz_id}/questoes", response_model=QuestaoOut, status_code=201)
async def criar_questao(
    quiz_id: uuid.UUID,
    body: QuestaoCreate,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

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
async def editar_questao(
    questao_id: uuid.UUID,
    body: QuestaoCreate,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
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
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        text("DELETE FROM respostas_questoes WHERE questao_id = :qid"),
        {"qid": questao_id}
    )
    await db.execute(
        text("DELETE FROM alternativas WHERE questao_id = :qid"),
        {"qid": questao_id}
    )
    await db.execute(
        text("DELETE FROM questoes WHERE id = :qid"),
        {"qid": questao_id}
    )
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