"""
Rota de upload de imagens para o Cloudinary.
Usa CLOUDINARY_URL do .env para evitar problemas com caracteres especiais no cloud name.
"""
import hashlib
import hmac
import logging
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import get_settings
from app.models.models import Usuario
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _parse_cloudinary_url(url: str):
    """
    Extrai cloud_name, api_key e api_secret da CLOUDINARY_URL.
    Formato: cloudinary://api_key:api_secret@cloud_name
    """
    parsed = urlparse(url)
    return {
        "cloud_name": parsed.hostname,
        "api_key": parsed.username,
        "api_secret": parsed.password,
    }


@router.post("/questao-imagem")
async def upload_questao_imagem(
    file: UploadFile = File(...),
    user: Usuario = Depends(get_current_user),
):
    settings = get_settings()

    # Tenta usar CLOUDINARY_URL primeiro, depois fallback para variáveis individuais
    if settings.CLOUDINARY_URL:
        creds = _parse_cloudinary_url(settings.CLOUDINARY_URL)
        cloud_name = creds["cloud_name"]
        api_key    = creds["api_key"]
        api_secret = creds["api_secret"]
    elif settings.CLOUDINARY_CLOUD_NAME:
        cloud_name = settings.CLOUDINARY_CLOUD_NAME
        api_key    = settings.CLOUDINARY_API_KEY
        api_secret = settings.CLOUDINARY_API_SECRET
    else:
        raise HTTPException(
            status_code=503,
            detail="Serviço de upload não configurado. Defina CLOUDINARY_URL no .env",
        )

    logger.info("Cloudinary cloud_name: %s | api_key: %s", cloud_name, api_key)

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo não permitido: {file.content_type}. Use JPEG, PNG, GIF ou WebP.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Arquivo muito grande. Máximo: 5 MB.")

    # Assinatura — parâmetros em ordem alfabética
    timestamp = int(time.time())
    folder = "adaptia/questoes"
    params_to_sign = f"folder={folder}&timestamp={timestamp}"
    signature = hmac.new(
        api_secret.encode(),
        params_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                upload_url,
                data={
                    "api_key": api_key,
                    "timestamp": str(timestamp),
                    "folder": folder,
                    "signature": signature,
                },
                files={"file": (file.filename or "upload.jpg", content, file.content_type)},
            )

        logger.info("Cloudinary status: %s | response: %s", response.status_code, response.text[:300])

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
        logger.exception("Erro de conexão: %s", e)
        raise HTTPException(status_code=502, detail=f"Erro de conexão: {e}")
