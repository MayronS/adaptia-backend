from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.database import get_db
from app.models.models import Usuario, ProgressoTopico, Topico, StatusProgresso
from app.schemas.schemas import LoginRequest, Token, UsuarioCreate, UsuarioOut
from app.services.auth_service import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["autenticação"])


@router.post("/login", response_model=Token)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Autentica o usuário e retorna um JWT."""
    res  = await db.execute(select(Usuario).where(Usuario.email == body.email))
    user = res.scalar_one_or_none()

    if not user or not verify_password(body.password, user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
        )
    if not user.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta desativada")

    user.ultimo_acesso = datetime.utcnow()
    token = create_access_token(user.id, user.perfil)
    return Token(access_token=token)


@router.post("/register", response_model=UsuarioOut, status_code=201)
async def register(body: UsuarioCreate, db: AsyncSession = Depends(get_db)):
    """Cria um novo usuário e inicializa o progresso nos tópicos disponíveis."""
    # Verifica e-mail duplicado
    res = await db.execute(select(Usuario).where(Usuario.email == body.email))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="E-mail já cadastrado")

    user = Usuario(
        nome=body.nome,
        email=body.email,
        senha_hash=hash_password(body.password),
        perfil=body.perfil,
    )
    db.add(user)
    await db.flush()  # gera o UUID antes do próximo passo

    # Inicializa progresso: tópicos sem pré-requisito ficam 'disponivel', demais 'bloqueado'
    res_topicos = await db.execute(select(Topico).where(Topico.ativo == True))
    topicos = res_topicos.scalars().all()

    for topico in topicos:
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
