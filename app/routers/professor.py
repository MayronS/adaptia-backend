import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    Usuario, PerfilUsuario, TentativaQuiz, ProgressoTopico, Materia, Topico, Quiz
)
from app.schemas.schemas import (
    DashboardProfessorOut, AlunoResumoOut, UsuarioOut,
    MateriaOut, TopicoOut, QuizOut,
)
from app.services.auth_service import require_professor

router = APIRouter(prefix="/professor", tags=["professor"])


# ── Dashboard da turma ────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardProfessorOut)
async def dashboard(
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    # Todos os alunos ativos (via tabela de vínculos de perfis)
    from app.models.models import UsuarioPerfil
    from sqlalchemy.orm import selectinload
    res = await db.execute(
        select(Usuario)
        .join(UsuarioPerfil, UsuarioPerfil.usuario_id == Usuario.id)
        .where(
            UsuarioPerfil.perfil == PerfilUsuario.aluno,
            UsuarioPerfil.ativo  == True,
            Usuario.ativo        == True,
        )
        .options(selectinload(Usuario.perfis))
    )
    alunos = res.scalars().all()

    resumos: list[AlunoResumoOut] = []
    precisam_apoio = 0

    for aluno in alunos:
        res_tent = await db.execute(
            select(TentativaQuiz).where(TentativaQuiz.usuario_id == aluno.id)
        )
        tentativas = res_tent.scalars().all()

        total_q  = sum(t.total_questoes for t in tentativas)
        acertos  = sum(t.acertos for t in tentativas)
        media    = round(sum(t.pontuacao for t in tentativas) / max(len(tentativas), 1), 1)
        taxa     = round(acertos / max(total_q, 1) * 100, 1)

        if media < 50 or taxa < 40:
            precisam_apoio += 1

        resumos.append(AlunoResumoOut(
            usuario=UsuarioOut.from_usuario(aluno),
            pontuacao_media=media,
            taxa_acerto_pct=taxa,
            total_tentativas=len(tentativas),
            ultimo_acesso=aluno.ultimo_acesso,
        ))

    media_turma = round(
        sum(r.pontuacao_media for r in resumos) / max(len(resumos), 1), 1
    )

    from datetime import datetime, timedelta
    sete_dias = datetime.utcnow() - timedelta(days=7)
    alunos_ativos = sum(
        1 for r in resumos
        if r.ultimo_acesso and r.ultimo_acesso >= sete_dias
    )

    return DashboardProfessorOut(
        media_turma=media_turma,
        total_alunos=len(alunos),
        alunos_ativos=alunos_ativos,
        precisam_apoio=precisam_apoio,
        alunos=sorted(resumos, key=lambda x: x.pontuacao_media, reverse=True),
    )


# ── Detalhe de um aluno ────────────────────────────────────────────────────────

@router.get("/alunos/{aluno_id}/progresso")
async def progresso_aluno(
    aluno_id: uuid.UUID,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(ProgressoTopico)
        .options(selectinload(ProgressoTopico.topico))
        .where(ProgressoTopico.usuario_id == aluno_id)
    )
    progressos = res.scalars().all()

    return [
        {
            "topico":       p.topico.titulo,
            "status":       p.status,
            "pontuacao":    p.pontuacao,
            "iniciado_em":  p.iniciado_em,
            "concluido_em": p.concluido_em,
        }
        for p in progressos
    ]


@router.get("/alunos/{aluno_id}/tentativas")
async def tentativas_aluno(
    aluno_id: uuid.UUID,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(TentativaQuiz)
        .options(selectinload(TentativaQuiz.quiz))
        .where(TentativaQuiz.usuario_id == aluno_id)
        .order_by(TentativaQuiz.realizado_em.desc())
        .limit(30)
    )
    tentativas = res.scalars().all()

    return [
        {
            "quiz":            t.quiz.titulo,
            "pontuacao":       t.pontuacao,
            "acertos":         t.acertos,
            "total_questoes":  t.total_questoes,
            "taxa_acerto_pct": round(t.acertos / max(t.total_questoes, 1) * 100, 1),
            "tempo_gasto_seg": t.tempo_gasto_seg,
            "realizado_em":    t.realizado_em,
        }
        for t in tentativas
    ]


# ── Gestão de conteúdo ────────────────────────────────────────────────────────

@router.get("/materias", response_model=list[MateriaOut])
async def listar_materias(
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Materia).where(Materia.ativo == True).order_by(Materia.ordem))
    return res.scalars().all()


@router.get("/materias/{materia_id}/topicos", response_model=list[TopicoOut])
async def listar_topicos(
    materia_id: uuid.UUID,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Topico)
        .where(Topico.materia_id == materia_id, Topico.ativo == True)
        .order_by(Topico.ordem)
    )
    return res.scalars().all()


@router.get("/topicos/{topico_id}/quizzes", response_model=list[QuizOut])
async def listar_quizzes(
    topico_id: uuid.UUID,
    _:  Usuario = Depends(require_professor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Quiz).where(Quiz.topico_id == topico_id).order_by(Quiz.criado_em)
    )
    return res.scalars().all()
