from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import get_settings
from app.database import engine, Base
from app.routers import auth, aluno, professor, admin, turmas

# Importa todos os models para garantir que estão registrados no metadata
from app.models import models  # noqa: F401

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cria tabelas e tipos ENUM automaticamente se não existirem
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    # Pre-aquece o bcrypt para evitar lentidão/timeout na primeira requisição de login.
    from app.services.auth_service import hash_password, verify_password
    _dummy_hash = hash_password("warmup")
    verify_password("warmup", _dummy_hash)

    yield

    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="API da Plataforma de Conteúdo Adaptativo — Projeto Extensionista 2026/1",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(aluno.router)
app.include_router(professor.router)
app.include_router(admin.router)
app.include_router(turmas.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/", tags=["status"])
async def root():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}

@app.get("/health", tags=["status"])
async def health():
    """Health check que também acorda o Neon se estiver hibernando."""
    from sqlalchemy import text
    from app.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return {"status": "healthy", "db": db_status}