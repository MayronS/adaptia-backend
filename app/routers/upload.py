"""
Rota de upload de imagens para o Cloudinary.
Utilizada por admin e professor ao criar/editar questões de quiz.
"""
import hashlib
import hmac
import time
import httpx

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from app.config import get_settings
from app.models.models import Usuario
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/questao-imagem")
async def upload_questao_imagem(
    file: UploadFile = File(...),
    user: Usuario = Depends(get_current_user),
):
    """
    Faz upload de uma imagem para o Cloudinary e retorna a URL segura.
    Acessível por admin e professor autenticados.
    """
    settings = get_settings()

    if not settings.CLOUDINARY_CLOUD_NAME:
        raise HTTPException(
            status_code=503,
            detail="Serviço de upload não configurado. Defina as variáveis CLOUDINARY_* no .env",
        )

    # Valida tipo
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo de arquivo não permitido: {file.content_type}. Use JPEG, PNG, GIF ou WebP.",
        )

    # Lê e valida tamanho
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Arquivo muito grande. Máximo: 5 MB.",
        )

    # Monta a assinatura para upload autenticado
    timestamp = int(time.time())
    folder = "adaptia/questoes"
    params_to_sign = f"folder={folder}&timestamp={timestamp}"
    signature = hmac.new(
        settings.CLOUDINARY_API_SECRET.encode(),
        params_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Envia para o Cloudinary via API REST
    upload_url = f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload"

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            upload_url,
            data={
                "api_key": settings.CLOUDINARY_API_KEY,
                "timestamp": timestamp,
                "folder": folder,
                "signature": signature,
            },
            files={"file": (file.filename, content, file.content_type)},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Erro ao enviar imagem para o Cloudinary: {response.text}",
        )

    data = response.json()
    return {
        "url": data["secure_url"],
        "public_id": data["public_id"],
        "width": data.get("width"),
        "height": data.get("height"),
    }
