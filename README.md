# AdaptIA — Backend

API REST da plataforma de aprendizado adaptativo AdaptIA. O sistema oferece recomendações personalizadas de conteúdo para alunos com base em seu desempenho, utilizando filtragem colaborativa e análise de erros com IA generativa.

---

## Índice

- [Visão Geral](#visão-geral)
- [Stack](#stack)
- [Arquitetura](#arquitetura)
- [Funcionalidades](#funcionalidades)
- [Endpoints da API](#endpoints-da-api)
- [Variáveis de Ambiente](#variáveis-de-ambiente)
- [Estrutura do Projeto](#estrutura-do-projeto)

---

## Visão Geral

O AdaptIA é uma plataforma educacional que adapta o conteúdo ao ritmo de cada aluno. O backend é responsável por:

- Autenticação com perfis múltiplos (aluno, professor, admin)
- Gerenciamento de matérias, tópicos, quizzes e questões
- Registro e análise de tentativas de quiz
- **Motor de recomendação híbrido**: 70% baseado na taxa de erro individual + 30% filtragem colaborativa por similaridade de cosseno
- **Geração de quizzes via IA** (Google Gemini): quiz diário personalizado e quiz por tópico específico
- Upload de imagens para questões via Supabase Storage
- Dashboard analítico para professores e alunos

---

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11 |
| Framework | FastAPI 0.111 |
| Servidor ASGI | Uvicorn |
| ORM | SQLAlchemy 2.0 (async) |
| Driver PostgreSQL | asyncpg |
| Banco de dados | PostgreSQL (serverless) |
| Autenticação | JWT via python-jose + bcrypt |
| IA Generativa | Google Gemini API |
| Storage | Supabase Storage |
| ML | scikit-learn (cosine similarity), numpy, pandas |
| Infra | Oracle Cloud (VM) + Docker |
| CI/CD | GitHub Actions |

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI App                         │
│                                                         │
│  /auth  /aluno  /professor  /admin  /turmas  /upload    │
│                                                         │
│        Services          │        Models                │
│  ┌─────────────────┐     │  ┌──────────────────────┐    │
│  │  auth_service   │     │  │  Usuario / Perfil    │    │
│  │  gemini_service │     │  │  Materia / Topico    │    │
│  │  recomendacao_  │     │  │  Quiz / Questao      │    │
│  │     service     │     │  │  Progresso / Turma   │    │
│  └─────────────────┘     │  └──────────────────────┘    │
└──────────────────────────┼──────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   PostgreSQL          Gemini API       Supabase Storage
                       (Quizzes IA)     (Imagens)
```

---

## Funcionalidades

### Autenticação
- Registro e login com JWT
- Suporte a múltiplos perfis por conta (ex: mesmo e-mail como aluno e professor)
- Seleção de perfil de sessão no login
- Troca de senha e recuperação via palavra-chave secreta

### Aluno
- Dashboard com estatísticas de desempenho
- Listagem de matérias e tópicos com progresso
- Realização de quizzes e registro de tentativas
- Análise de erros por tópico
- Recomendações personalizadas de revisão
- Quiz diário gerado por IA (cache de 24h)
- Quiz temático por tópico via IA
- Convites de turma (aceitar / recusar)

### Professor
- Dashboard com visão geral de turmas e alunos
- CRUD de matérias, tópicos, quizzes e questões
- Acompanhamento de progresso individual de alunos
- Gerenciamento de turmas e vínculos com alunos
- Associação de quizzes a turmas

### Admin
- CRUD completo de matérias e tópicos
- Painel de análise geral

### Upload
- Upload de imagens para questões (JPEG, PNG, GIF, WebP — até 5 MB)
- Armazenamento no Supabase Storage com URL pública
  
---

## Endpoints da API

### Autenticação — `/auth`

| Método | Rota | Descrição |
|---|---|---|
| POST | `/auth/register` | Cria nova conta
| POST | `/auth/login` | Login e geração de JWT
| GET | `/auth/me` | Dados do usuário logado
| POST | `/auth/adicionar-perfil` | Adiciona perfil à conta 
| POST | `/auth/alterar-senha` | Altera a senha
| POST | `/auth/recuperar-senha` | Recupera senha via palavra-chave
| POST | `/auth/palavra-chave` | Cadastra palavra-chave de recuperação
| GET | `/auth/palavra-chave-dica` | Retorna dica da palavra-chave


### Aluno — `/aluno`

| Método | Rota | Descrição |
|---|---|---|
| GET | `/aluno/dashboard` | Dashboard com estatísticas |
| GET | `/aluno/materias` | Lista matérias disponíveis |
| POST | `/aluno/materias/{id}/adicionar` | Matricula-se em uma matéria |
| DELETE | `/aluno/materias/{id}/remover` | Remove matrícula |
| GET | `/aluno/topicos` | Lista tópicos com progresso |
| GET | `/aluno/topicos/{id}/quizzes` | Quizzes de um tópico |
| POST | `/aluno/tentativas` | Registra tentativa de quiz |
| GET | `/aluno/tentativas/melhores` | Melhores resultados por quiz |
| GET | `/aluno/analise-erros` | Análise de erros por tópico |
| POST | `/aluno/recomendacoes/gerar` | Gera recomendações personalizadas |
| PATCH | `/aluno/recomendacoes/{id}/visualizar` | Marca recomendação como vista |
| GET | `/aluno/quiz-diario` | Quiz diário gerado por IA |
| POST | `/aluno/quiz-diario/concluir` | Conclui quiz diário |
| POST | `/aluno/quiz-ia` | Gera quiz de tópico via IA |
| POST | `/aluno/quiz-ia/concluir` | Conclui quiz de IA |
| GET | `/aluno/convites` | Lista convites de turma |
| PATCH | `/aluno/convites/{id}/responder` | Aceita ou recusa convite |

### Professor — `/professor`

| Método | Rota | Descrição |
|---|---|---|
| GET | `/professor/dashboard` | Dashboard geral |
| GET | `/professor/materias` | Lista matérias do professor |
| POST | `/professor/materias` | Cria nova matéria |
| PUT | `/professor/materias/{id}` | Atualiza matéria |
| DELETE | `/professor/materias/{id}` | Remove matéria |
| GET/POST/PUT/DELETE | `/professor/materias/{id}/topicos` | CRUD de tópicos |
| GET/POST/PUT/DELETE | `/professor/topicos/{id}/quizzes` | CRUD de quizzes |
| POST/PUT/DELETE | `/professor/quizzes/{id}/questoes` | CRUD de questões |
| GET | `/professor/alunos/{id}/progresso` | Progresso de um aluno |
| GET | `/professor/alunos/{id}/tentativas` | Tentativas de um aluno |
| GET | `/professor/alunos-vinculados` | Lista alunos vinculados |

### Turmas — `/turmas`

| Método | Rota | Descrição |
|---|---|---|
| GET | `/turmas/professor` | Lista turmas do professor |
| POST | `/turmas/professor` | Cria nova turma |
| PUT | `/turmas/professor/{id}` | Atualiza turma |
| DELETE | `/turmas/professor/{id}` | Remove turma |
| POST | `/turmas/professor/{id}/alunos/{aluno_id}` | Adiciona aluno à turma |
| DELETE | `/turmas/professor/{id}/alunos/{aluno_id}` | Remove aluno da turma |
| POST/PUT/DELETE | `/turmas/professor/quizzes` | CRUD de quizzes de turma |
| GET | `/turmas/aluno` | Turmas do aluno |
| POST | `/turmas/aluno/tentativas` | Registra tentativa de quiz de turma |

### Admin — `/admin`

| Método | Rota | Descrição |
|---|---|---|
| GET/POST/PUT/DELETE | `/admin/materias` | CRUD de matérias |
| GET/POST/PUT/DELETE | `/admin/materias/{id}/topicos` | CRUD de tópicos |
| GET/POST/PUT/DELETE | `/admin/topicos/{id}/quizzes` | CRUD de quizzes |
| GET | `/admin/analise` | Painel de análise geral |

### Upload — `/upload`

| Método | Rota | Descrição |
|---|---|---|
| POST | `/upload/questao-imagem` | Upload de imagem para questão |

### Status

| Método | Rota | Descrição |
|---|---|---|
| GET | `/` | Status da aplicação |
| GET | `/health` | Health check com verificação do banco |

---

## Variáveis de Ambiente

```
# Banco de dados
DATABASE_URL

# Segurança JWT
SECRET_KEY
ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES

# Aplicação
APP_NAME
APP_ENV
CORS_ORIGINS

# Google Gemini (geração de quizzes por IA)
GEMINI_API_KEY

# Supabase Storage
SUPABASE_URL
SUPABASE_ANON_KEY
```

---

## Estrutura do Projeto

```
adaptia-backend/
├── .github/
│   └── workflows/
│       └── deploy.yml          # CI/CD para Oracle Cloud
├── app/
│   ├── __init__.py
│   ├── main.py                 # Entrypoint da aplicação FastAPI
│   ├── config.py               # Configurações via pydantic-settings
│   ├── database.py             # Engine, sessão e Base do SQLAlchemy
│   ├── models/
│   │   └── models.py           # Modelos ORM (tabelas e enums)
│   ├── schemas/
│   │   └── schemas.py          # Schemas Pydantic (request/response)
│   ├── routers/
│   │   ├── auth.py             # Autenticação e gerenciamento de conta
│   │   ├── aluno.py            # Rotas do perfil aluno
│   │   ├── professor.py        # Rotas do perfil professor
│   │   ├── admin.py            # Rotas administrativas
│   │   ├── turmas.py           # Gerenciamento de turmas
│   │   └── upload.py           # Upload de imagens
│   └── services/
│       ├── auth_service.py     # JWT, bcrypt, dependências de auth
│       ├── gemini_service.py   # Integração com Google Gemini API
│       └── recomendacao_service.py  # Motor de recomendação híbrido
├── Dockerfile
├── .dockerignore
├── requirements.txt
└── README.md
```

---

## Licença

Este projeto foi desenvolvido como parte do **Projeto Extensionista 2026/1**. Todos os direitos reservados.
