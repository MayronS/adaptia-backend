from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime

from app.database import get_db
from app.models.models import Usuario, UsuarioPerfil, ProgressoTopico, Topico, StatusProgresso, PerfilUsuario
from app.schemas.schemas import (
    LoginRequest, Token, UsuarioCreate, UsuarioOut,
    AdicionarPerfilRequest,
)
from app.services.auth_service import (
    hash_password, verify_password, create_access_token, get_current_user,
)

router = APIRouter(prefix="/auth", tags=["autenticação"])

ADMIN_SUFFIX = "/admin"


def _carregar_usuario_com_perfis(query):
    """Helper para sempre carregar a relação 'perfis' junto com o usuário."""
    return query.options(selectinload(Usuario.perfis))


@router.post("/login", response_model=Token)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Autentica o usuário e retorna um JWT.

    - Se o usuário tiver apenas um perfil, ele é usado automaticamente.
    - Se tiver múltiplos perfis, informe o campo `perfil` no body para
      selecionar qual sessão abrir (ex: "aluno" ou "professor").
    - Login de administrador: use o e-mail com sufixo /admin.
    """
    email_raw  = body.email.strip()
    is_admin   = email_raw.endswith(ADMIN_SUFFIX)
    email_real = email_raw[: -len(ADMIN_SUFFIX)] if is_admin else email_raw

    res  = await db.execute(
        _carregar_usuario_com_perfis(select(Usuario).where(Usuario.email == email_real))
    )
    user = res.scalar_one_or_none()

    if not user or not verify_password(body.password, user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
        )

    if not user.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta desativada")

    perfis_ativos = user.get_perfis_ativos()

    # Login com /admin: exige perfil admin
    if is_admin:
        if PerfilUsuario.admin not in perfis_ativos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta conta não tem permissão de administrador",
            )
        perfil_sessao = PerfilUsuario.admin

    else:
        if not perfis_ativos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nenhum perfil ativo encontrado para esta conta",
            )

        if len(perfis_ativos) == 1:
            # Apenas um perfil: usa automaticamente
            perfil_sessao = perfis_ativos[0]
        else:
            # Múltiplos perfis: exige que o cliente informe qual usar
            if body.perfil is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": "Este usuário possui múltiplos perfis. Informe o campo 'perfil' para selecionar.",
                        "perfis_disponiveis": [p.value for p in perfis_ativos],
                    },
                )
            if body.perfil not in perfis_ativos:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Perfil '{body.perfil.value}' não encontrado nesta conta",
                )
            perfil_sessao = body.perfil

    user.ultimo_acesso = datetime.utcnow()
    token = create_access_token(user.id, perfil_sessao)

    return Token(
        access_token=token,
        perfis=perfis_ativos,
    )


@router.post("/register", response_model=UsuarioOut, status_code=201)
async def register(body: UsuarioCreate, db: AsyncSession = Depends(get_db)):
    """
    Cria um novo usuário ou adiciona um perfil a uma conta existente.

    - Se o e-mail NÃO existir: cria o usuário com o perfil informado.
    - Se o e-mail JÁ existir e o perfil for diferente: adiciona o novo perfil
      à conta existente (exige a mesma senha para confirmar identidade).
    - Se o e-mail e perfil já existirem: retorna erro 409.
    - Perfil 'admin' não pode ser criado por esta rota.
    """
    if body.perfil == PerfilUsuario.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil administrador não pode ser criado por esta rota",
        )

    res = await db.execute(
        _carregar_usuario_com_perfis(select(Usuario).where(Usuario.email == body.email))
    )
    existing = res.scalar_one_or_none()

    if existing:
        # E-mail já cadastrado — tenta adicionar novo perfil
        if not verify_password(body.password, existing.senha_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Senha incorreta para este e-mail",
            )
        if existing.tem_perfil(body.perfil):
            raise HTTPException(
                status_code=409,
                detail=f"Este e-mail já possui o perfil '{body.perfil.value}'",
            )
        # Adiciona o novo perfil
        novo_perfil = UsuarioPerfil(usuario_id=existing.id, perfil=body.perfil)
        db.add(novo_perfil)
        await db.flush()

        # Se for aluno, inicializa progresso nos tópicos
        if body.perfil == PerfilUsuario.aluno:
            await _inicializar_progresso_aluno(existing.id, db)

        await db.commit()
        await db.refresh(existing)
        return UsuarioOut.from_usuario(existing)

    # Novo usuário
    user = Usuario(
        nome=body.nome,
        email=body.email,
        senha_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()  # gera o ID

    perfil_obj = UsuarioPerfil(usuario_id=user.id, perfil=body.perfil)
    db.add(perfil_obj)

    if body.perfil == PerfilUsuario.aluno:
        await _inicializar_progresso_aluno(user.id, db)

    await db.commit()
    await db.refresh(user, ["perfis"])
    return UsuarioOut.from_usuario(user)


@router.post("/adicionar-perfil", response_model=UsuarioOut)
async def adicionar_perfil(
    body: AdicionarPerfilRequest,
    db:   AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """
    Adiciona um novo perfil ao usuário autenticado.
    Útil para usuários que já estão logados e querem ativar o perfil professor (ou aluno).
    """
    if body.perfil == PerfilUsuario.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil administrador não pode ser adicionado por esta rota",
        )

    # Recarrega com perfis
    res = await db.execute(
        _carregar_usuario_com_perfis(select(Usuario).where(Usuario.id == user.id))
    )
    user = res.scalar_one()

    if user.tem_perfil(body.perfil):
        raise HTTPException(
            status_code=409,
            detail=f"Você já possui o perfil '{body.perfil.value}'",
        )

    novo_perfil = UsuarioPerfil(usuario_id=user.id, perfil=body.perfil)
    db.add(novo_perfil)

    if body.perfil == PerfilUsuario.aluno:
        await _inicializar_progresso_aluno(user.id, db)

    await db.commit()
    await db.refresh(user, ["perfis"])
    return UsuarioOut.from_usuario(user)


async def _inicializar_progresso_aluno(usuario_id, db: AsyncSession):
    """Cria registros de progresso para todos os tópicos ativos."""
    res_topicos = await db.execute(select(Topico).where(Topico.ativo == True))
    for topico in res_topicos.scalars().all():
        status_inicial = (
            StatusProgresso.disponivel
            if topico.prerequisito_id is None
            else StatusProgresso.bloqueado
        )
        db.add(ProgressoTopico(
            usuario_id=usuario_id,
            topico_id=topico.id,
            status=status_inicial,
        ))
