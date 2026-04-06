"""
Serviço de geração de quizzes via Google Gemini API (gratuita).
"""
import json
import httpx
from app.config import get_settings

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


async def gerar_quiz_topico(topico_nome: str, materia_nome: str, nivel: int, n_questoes: int = 5) -> list[dict]:
    """
    Chama a API do Gemini para gerar questões de múltipla escolha sobre um tópico.
    Retorna lista de questões no formato interno do sistema.
    """
    settings = get_settings()
    api_key = settings.GEMINI_API_KEY

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
            "maxOutputTokens": 2048,
        }
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GEMINI_URL}?key={api_key}",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

    data = resp.json()
    texto = data["candidates"][0]["content"]["parts"][0]["text"]

    # Remove possíveis blocos de markdown caso o modelo ignore a instrução
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    texto = texto.strip()

    questoes = json.loads(texto)
    return questoes[:n_questoes]
