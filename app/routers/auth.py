from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.database import get_db
from app.models.models import Usuario, ProgressoTopico, Topico, StatusProgresso, PerfilUsuario
from app.schemas.schemas import LoginRequest, Token, UsuarioCreate, UsuarioOut
from app.services.auth_service import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["autenticação"])

ADMIN_SUFFIX = "/admin"


@router.post("/login", response_model=Token)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Autentica o usuário e retorna um JWT.

    Login de administrador:
      - E-mail informado com sufixo /admin (ex: usuario@email.com/admin)
      - O sistema remove o sufixo, busca o usuário pelo e-mail real
      - Exige que o perfil cadastrado no banco seja 'admin'
    """
    email_raw  = body.email.strip()
    is_admin   = email_raw.endswith(ADMIN_SUFFIX)
    email_real = email_raw[: -len(ADMIN_SUFFIX)] if is_admin else email_raw

    res  = await db.execute(select(Usuario).where(Usuario.email == email_real))
    user = res.scalar_one_or_none()

    if not user or not verify_password(body.password, user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
        )

    if not user.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta desativada")

    # Login com /admin: exige perfil admin no banco
    if is_admin:
        if user.perfil != PerfilUsuario.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta conta não tem permissão de administrador",
            )

    user.ultimo_acesso = datetime.utcnow()
    token = create_access_token(user.id, user.perfil)
    return Token(access_token=token)


@router.post("/register", response_model=UsuarioOut, status_code=201)
async def register(body: UsuarioCreate, db: AsyncSession = Depends(get_db)):
    """
    Cria um novo usuário (aluno ou professor).
    Perfil 'admin' NÃO pode ser criado por esta rota —
    deve ser promovido manualmente no banco de dados.
    """
    # Impede criação direta de admin pela API
    if body.perfil == PerfilUsuario.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil administrador não pode ser criado por esta rota",
        )

    # Verifica e-mail duplicado para o mesmo perfil
    res = await db.execute(
        select(Usuario).where(
            Usuario.email  == body.email,
            Usuario.perfil == body.perfil,
        )
    )
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="E-mail já cadastrado para este perfil")

    user = Usuario(
        nome=body.nome,
        email=body.email,
        senha_hash=hash_password(body.password),
        perfil=body.perfil,
    )
    db.add(user)
    await db.flush()

    # Inicializa progresso apenas para alunos
    if body.perfil == PerfilUsuario.aluno:
        res_topicos = await db.execute(select(Topico).where(Topico.ativo == True))
        for topico in res_topicos.scalars().all():
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

    return user