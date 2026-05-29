"""
Rota de upload de imagens para o Supabase Storage.
"""
import logging
import mimetypes
import uuid

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import get_settings
from app.models.models import Usuario
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
BUCKET = "questoes"


@router.post("/questao-imagem")
async def upload_questao_imagem(
    file: UploadFile = File(...),
    user: Usuario = Depends(get_current_user),
):
    settings = get_settings()

    if not settings.SUPABASE_URL:
        raise HTTPException(
            status_code=503,
            detail="Serviço de upload não configurado. Defina SUPABASE_URL no .env",
        )

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo não permitido: {file.content_type}. Use JPEG, PNG, GIF ou WebP.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Arquivo muito grande. Máximo: 5 MB.")

    # Gera nome único para o arquivo
    ext = mimetypes.guess_extension(file.content_type) or ".jpg"
    ext = ext.replace(".jpe", ".jpg")
    filename = f"{uuid.uuid4().hex}{ext}"

    upload_url = f"{settings.SUPABASE_URL}/storage/v1/object/{BUCKET}/{filename}"

    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_ANON_KEY}",
        "Content-Type": file.content_type,
        "x-upsert": "true",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(upload_url, headers=headers, content=content)

        logger.info("Supabase status: %s | response: %s", response.status_code, response.text[:300])

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"Supabase retornou {response.status_code}: {response.text[:300]}",
            )

        public_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{filename}"

        return {
            "url": public_url,
            "path": filename,
        }

    except httpx.TimeoutException:
        logger.exception("Timeout ao conectar no Supabase")
        raise HTTPException(status_code=504, detail="Timeout ao conectar no Supabase.")
    except httpx.RequestError as e:
        logger.exception("Erro de conexão: %s", e)
        raise HTTPException(status_code=502, detail=f"Erro de conexão: {e}")
