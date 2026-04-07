
import json
import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"


async def gerar_quiz_topico(topico_nome: str, materia_nome: str, nivel: int, n_questoes: int = 5) -> list[dict]:
    settings = get_settings()
    api_key = settings.GEMINI_API_KEY

    if not api_key:
        raise ValueError("GEMINI_API_KEY não configurada. Adicione a variável de ambiente no Fly.io.")

    prompt = f"""Você é um professor de {materia_nome} preparando uma revisão para um aluno com dificuldades no tópico "{topico_nome}".

Gere exatamente {n_questoes} questões de múltipla escolha em português brasileiro sobre "{topico_nome}".
Nível de dificuldade: {nivel}/5.

Responda APENAS com um JSON válido, sem markdown, sem explicações fora do JSON. Formato exato:
[
  {{
    "enunciado": "Texto da pergunta aqui?",
    "alternativas": [
      {{"texto": "Alternativa A", "correta": true, "explicacao": "Explicação breve do por quê está correta"}},
      {{"texto": "Alternativa B", "correta": false, "explicacao": ""}},
      {{"texto": "Alternativa C", "correta": false, "explicacao": ""}},
      {{"texto": "Alternativa D", "correta": false, "explicacao": ""}}
    ]
  }}
]

Regras:
- Exatamente {n_questoes} questões
- Exatamente 4 alternativas por questão
- Exatamente 1 alternativa correta por questão
- Questões claras, objetivas e pedagogicamente corretas
- Foque nos conceitos que alunos costumam errar sobre "{topico_nome}"
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        }
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={api_key}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code != 200:
                body = resp.text
                logger.error(f"Gemini retornou {resp.status_code}: {body}")
                raise ValueError(f"Gemini API erro {resp.status_code}: {body[:300]}")

            data = resp.json()

    except httpx.TimeoutException:
        raise ValueError("Timeout ao chamar a API do Gemini. Tente novamente.")
    except httpx.RequestError as e:
        raise ValueError(f"Erro de conexão com o Gemini: {str(e)}")

    try:
        texto = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        logger.error(f"Resposta inesperada do Gemini: {data}")
        raise ValueError(f"Resposta inesperada do Gemini: {str(data)[:300]}")

    # Remove blocos markdown se o modelo os incluir
    texto = texto.strip()
    if texto.startswith("```"):
        partes = texto.split("```")
        # Pega o conteúdo entre os backticks
        texto = partes[1] if len(partes) > 1 else texto
        if texto.startswith("json"):
            texto = texto[4:]
    texto = texto.strip()

    try:
        questoes = json.loads(texto)
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido do Gemini: {texto[:500]}")
        raise ValueError(f"O Gemini retornou um JSON inválido: {str(e)}")

    if not isinstance(questoes, list) or len(questoes) == 0:
        raise ValueError("O Gemini não retornou questões no formato esperado.")

    return questoes[:n_questoes]
