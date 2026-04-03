from datetime import datetime, timedelta
from typing import Optional
import uuid

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.models.models import Usuario, PerfilUsuario
from app.schemas.schemas import TokenData

settings      = get_settings()
pwd_context   = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Senha ─────────────────────────────────────────────────────────────────────

def _truncate(password: str) -> str:
    """bcrypt suporta no máximo 72 bytes — trunca silenciosamente se necessário."""
    encoded = password.encode("utf-8")
    return encoded[:72].decode("utf-8", errors="ignore")

def hash_password(password: str) -> str:
    return pwd_context.hash(_truncate(password))

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(_truncate(plain), hashed)


# ── Token JWT ─────────────────────────────────────────────────────────────────

def create_access_token(usuario_id: uuid.UUID, perfil_ativo: PerfilUsuario) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub":          str(usuario_id),
        "perfil_ativo": perfil_ativo.value,  # perfil desta sessão
        "exp":          expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return TokenData(
            usuario_id=uuid.UUID(payload["sub"]),
            perfil_ativo=PerfilUsuario(payload["perfil_ativo"]),
        )
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Dependências FastAPI ──────────────────────────────────────────────────────

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db:    AsyncSession = Depends(get_db),
) -> Usuario:
    token_data = decode_token(token)
    result = await db.execute(
        select(Usuario)
        .options(selectinload(Usuario.perfis))
        .where(Usuario.id == token_data.usuario_id)
    )
    user = result.scalar_one_or_none()
    if not user or not user.ativo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")
    user.ultimo_acesso = datetime.utcnow()
    return user

async def require_aluno(
    token: str = Depends(oauth2_scheme),
    db:    AsyncSession = Depends(get_db),
) -> Usuario:
    """Exige que o perfil ATIVO nesta sessão seja aluno (ou admin)."""
    token_data = decode_token(token)
    if token_data.perfil_ativo not in (PerfilUsuario.aluno, PerfilUsuario.admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a alunos")
    result = await db.execute(
        select(Usuario)
        .options(selectinload(Usuario.perfis))
        .where(Usuario.id == token_data.usuario_id)
    )
    user = result.scalar_one_or_none()
    if not user or not user.ativo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")
    user.ultimo_acesso = datetime.utcnow()
    return user

async def require_professor(
    token: str = Depends(oauth2_scheme),
    db:    AsyncSession = Depends(get_db),
) -> Usuario:
    """Exige que o perfil ATIVO nesta sessão seja professor (ou admin)."""
    token_data = decode_token(token)
    if token_data.perfil_ativo not in (PerfilUsuario.professor, PerfilUsuario.admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a professores")
    result = await db.execute(
        select(Usuario)
        .options(selectinload(Usuario.perfis))
        .where(Usuario.id == token_data.usuario_id)
    )
    user = result.scalar_one_or_none()
    if not user or not user.ativo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")
    user.ultimo_acesso = datetime.utcnow()
    return user
