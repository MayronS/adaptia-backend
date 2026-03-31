from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
 
from app.config import get_settings
from app.database import engine, Base
from app.routers import auth, aluno, professor
 
# Importa todos os models para garantir que estão registrados no metadata
from app.models import models  # noqa: F401
 
settings = get_settings()
 
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cria tabelas e tipos ENUM automaticamente se não existirem
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
 
 
# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/", tags=["status"])
async def root():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}
 
@app.get("/health", tags=["status"])
async def health():
    return {"status": "healthy"}
 