from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
 
settings = get_settings()
 
 
def _clean_database_url(url: str) -> tuple[str, dict]:
    """
    Remove parâmetros incompatíveis com asyncpg da URL
    e retorna a URL limpa + connect_args com SSL configurado.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
 
    # Parâmetros que o asyncpg NÃO aceita na URL
    incompatible = {"sslmode", "ssl", "channel_binding", "options"}
    needs_ssl = bool(params.get("sslmode") or params.get("ssl"))
 
    # Remove os parâmetros incompatíveis
    clean_params = {k: v for k, v in params.items() if k not in incompatible}
    clean_query = urlencode(clean_params, doseq=True)
    clean_url = urlunparse(parsed._replace(query=clean_query))
 
    connect_args = {}
    if needs_ssl:
        import ssl
        ctx = ssl.create_default_context()
        connect_args["ssl"] = ctx
 
    return clean_url, connect_args
 
 
clean_url, connect_args = _clean_database_url(settings.DATABASE_URL)
 
engine = create_async_engine(
    clean_url,
    echo=settings.APP_ENV == "development",
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,    # testa a conexão antes de usar — evita "connection closed" no cold start
    pool_recycle=1800,     # recicla conexões a cada 30min — evita timeout por inatividade
    connect_args=connect_args,
)
 
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
 
 
class Base(DeclarativeBase):
    pass
 
 
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()