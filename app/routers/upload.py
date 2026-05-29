"""
Rota de upload de imagens para o Cloudinary.
"""
import hashlib
import hmac
import logging
import time

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import get_settings
from app.models.models import Usuario
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/questao-imagem")
async def upload_questao_imagem(
    file: UploadFile = File(...),
    user: Usuario = Depends(get_current_user),
):
    settings = get_settings()

    if not settings.CLOUDINARY_CLOUD_NAME:
        raise HTTPException(
            status_code=503,
            detail="Serviço de upload não configurado. Defina CLOUDINARY_* no .env",
        )

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo não permitido: {file.content_type}. Use JPEG, PNG, GIF ou WebP.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Arquivo muito grande. Máximo: 5 MB.")

    # Assinatura Cloudinary — parâmetros em ordem alfabética
    timestamp = int(time.time())
    folder = "adaptia/questoes"

    # Parâmetros ordenados alfabeticamente conforme exige o Cloudinary
    params_to_sign = f"folder={folder}&timestamp={timestamp}"
    signature = hmac.new(
        settings.CLOUDINARY_API_SECRET.encode(),
        params_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    upload_url = (
        f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                upload_url,
                data={
                    "api_key": settings.CLOUDINARY_API_KEY,
                    "timestamp": str(timestamp),
                    "folder": folder,
                    "signature": signature,
                },
                files={"file": (file.filename or "upload.jpg", content, file.content_type)},
            )

        logger.info("Cloudinary status: %s", response.status_code)
        logger.info("Cloudinary response: %s", response.text[:500])

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Cloudinary retornou {response.status_code}: {response.text[:300]}",
            )

        data = response.json()
        return {
            "url": data["secure_url"],
            "public_id": data["public_id"],
            "width": data.get("width"),
            "height": data.get("height"),
        }

    except httpx.TimeoutException:
        logger.exception("Timeout ao conectar no Cloudinary")
        raise HTTPException(status_code=504, detail="Timeout ao conectar no Cloudinary.")
    except httpx.RequestError as e:
        logger.exception("Erro de conexão com Cloudinary: %s", e)
        raise HTTPException(status_code=502, detail=f"Erro de conexão: {e}")
