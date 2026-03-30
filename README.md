# AdaptIA — Backend (FastAPI)

Projeto Extensionista 2026/1 · Sistemas de Informação · Faculdade Uniessa

---

## 📁 Estrutura do projeto

```
adaptia-backend/
├── requirements.txt
├── .env.example
└── app/
    ├── main.py              ← Entrada da aplicação + CORS
    ├── config.py            ← Variáveis de ambiente (Pydantic Settings)
    ├── database.py          ← Conexão assíncrona com PostgreSQL
    ├── models/
    │   └── models.py        ← ORM SQLAlchemy (10 tabelas + ENUMs)
    ├── schemas/
    │   └── schemas.py       ← Validação de entrada/saída (Pydantic v2)
    ├── services/
    │   ├── auth_service.py          ← JWT + bcrypt + dependências FastAPI
    │   └── recomendacao_service.py  ← Motor de IA (filtragem colaborativa)
    └── routers/
        ├── auth.py       ← POST /auth/login  |  POST /auth/register
        ├── aluno.py      ← GET  /aluno/dashboard  |  POST /aluno/tentativas ...
        └── professor.py  ← GET  /professor/dashboard  |  GET /professor/alunos/:id ...
```

---

## 🚀 Como rodar localmente

### 1. Clone e entre na pasta
```bash
cd adaptia-backend
```

### 2. Crie o ambiente virtual e instale dependências
```bash
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 3. Configure as variáveis de ambiente
```bash
cp .env.example .env
# Edite o .env com sua connection string do Neon e uma SECRET_KEY segura
```

### 4. Execute o servidor
```bash
uvicorn app.main:app --reload
```

Acesse: **http://localhost:8000/docs** → documentação interativa Swagger

---

## 🔐 Autenticação

A API usa **JWT Bearer Token**. O fluxo é:

```
POST /auth/register   → cria conta
POST /auth/login      → retorna { access_token, token_type }

# Todas as demais rotas exigem o header:
Authorization: Bearer <access_token>
```

---

## 📡 Endpoints principais

### Auth
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/auth/register` | Cria novo usuário |
| POST | `/auth/login` | Retorna JWT |

### Aluno
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/aluno/dashboard` | Métricas, progresso e recomendações |
| GET | `/aluno/topicos` | Lista tópicos com status de progresso |
| GET | `/aluno/topicos/{id}/quizzes` | Quizzes de um tópico (sem gabarito) |
| POST | `/aluno/tentativas` | Envia respostas, recebe resultado com gabarito |
| POST | `/aluno/recomendacoes/gerar` | Força regeneração das recomendações |
| PATCH | `/aluno/recomendacoes/{id}/visualizar` | Marca recomendação como vista |

### Professor
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/professor/dashboard` | Visão geral da turma |
| GET | `/professor/alunos/{id}/progresso` | Progresso detalhado de um aluno |
| GET | `/professor/alunos/{id}/tentativas` | Histórico de quizzes de um aluno |
| GET | `/professor/materias` | Lista matérias |
| GET | `/professor/materias/{id}/topicos` | Tópicos de uma matéria |
| GET | `/professor/topicos/{id}/quizzes` | Quizzes de um tópico |

---

## 🤖 Motor de Recomendação

O arquivo `app/services/recomendacao_service.py` implementa duas estratégias combinadas:

**Filtragem por conteúdo (peso 60%)**
Compara o nível de dificuldade dos tópicos disponíveis com o desempenho atual do aluno. Tópicos cuja dificuldade está próxima do nível estimado do aluno recebem score mais alto.

**Filtragem colaborativa (peso 40%)**
Calcula a similaridade de cosseno entre o vetor de pontuações do aluno e os vetores dos demais alunos usando `scikit-learn`. Tópicos que alunos similares já concluíram ganham bônus de score.

As recomendações são geradas automaticamente após cada tentativa de quiz e armazenadas na tabela `recomendacoes`.

---

## 🔄 Fluxo de progressão de tópicos

```
BLOQUEADO → DISPONÍVEL → EM_PROGRESSO → CONCLUÍDO
              ↑                              |
       pré-requisito                   desbloqueia
       concluído                       próximos tópicos
```

Quando o aluno atinge **70 pontos ou mais** em qualquer quiz de um tópico, o tópico é marcado como `concluido` e todos os tópicos que dependem dele são automaticamente desbloqueados.

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|--------|------------|
| Framework | FastAPI 0.111 |
| ORM | SQLAlchemy 2.0 (async) |
| Banco | PostgreSQL / Neon (asyncpg) |
| Validação | Pydantic v2 |
| Autenticação | JWT (python-jose) + bcrypt (passlib) |
| IA | scikit-learn (cosine_similarity) |
| Servidor | Uvicorn |

---

## ☁️ Deploy no Railway

```bash
# 1. Instale o Railway CLI
npm install -g @railway/cli

# 2. Login e link ao projeto
railway login
railway link

# 3. Configure as variáveis de ambiente no painel Railway
#    DATABASE_URL, SECRET_KEY, APP_ENV=production

# 4. Deploy
railway up
```

O Railway detecta automaticamente o Python e usa `uvicorn app.main:app` como comando de start.
Adicione um `Procfile` se necessário:
```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
