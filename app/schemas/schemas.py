from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from app.models.models import PerfilUsuario, StatusProgresso, TipoQuestao


# ── Helpers ──────────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type:   str = "bearer"

class TokenData(BaseModel):
    usuario_id: uuid.UUID
    perfil:     PerfilUsuario


# ── Usuário ──────────────────────────────────────────────────────────────────

class UsuarioCreate(BaseModel):
    nome:     str           = Field(..., min_length=2, max_length=120)
    email:    EmailStr
    password: str           = Field(..., min_length=6)
    perfil:   PerfilUsuario = PerfilUsuario.aluno

class UsuarioOut(OrmBase):
    id:            uuid.UUID
    nome:          str
    email:         str
    perfil:        PerfilUsuario
    ativo:         bool
    criado_em:     datetime
    ultimo_acesso: datetime | None = None


# ── Matéria ───────────────────────────────────────────────────────────────────

class MateriaOut(OrmBase):
    id:        uuid.UUID
    nome:      str
    descricao: str | None
    icone:     str | None
    cor:       str | None
    ordem:     int


# ── Tópico ───────────────────────────────────────────────────────────────────

class TopicoOut(OrmBase):
    id:                uuid.UUID
    materia_id:        uuid.UUID
    titulo:            str
    descricao:         str | None
    ordem:             int
    nivel_dificuldade: int
    prerequisito_id:   uuid.UUID | None = None
    ativo:             bool
    materia:           MateriaOut | None = None

class TopicoComProgressoOut(TopicoOut):
    status:    StatusProgresso | None = None
    pontuacao: int | None = None


# ── Quiz ─────────────────────────────────────────────────────────────────────

class QuizOut(OrmBase):
    id:               uuid.UUID
    topico_id:        uuid.UUID
    titulo:           str
    descricao:        str | None
    tempo_limite_seg: int | None
    pontuacao_maxima: int
    tentativas_max:   int | None
    ativo:            bool

class QuizComQuestoesOut(QuizOut):
    questoes: list[QuestaoOut] = []


# ── Questão ──────────────────────────────────────────────────────────────────

class AlternativaOut(OrmBase):
    id:         uuid.UUID
    texto:      str
    ordem:      int
    correta:    bool
    explicacao: str | None = None

class AlternativaComGabaritoOut(AlternativaOut):
    pass  # herda correta e explicacao de AlternativaOut

class QuestaoOut(OrmBase):
    id:           uuid.UUID
    enunciado:    str
    tipo:         TipoQuestao
    pontos:       int
    ordem:        int
    alternativas: list[AlternativaOut] = []


# ── Tentativa de Quiz ─────────────────────────────────────────────────────────

class RespostaItem(BaseModel):
    questao_id:         uuid.UUID
    alternativa_id:     uuid.UUID | None = None
    resposta_texto:     str | None       = None
    tempo_resposta_seg: int | None       = None

class TentativaCreate(BaseModel):
    quiz_id:         uuid.UUID
    tempo_gasto_seg: int | None = None
    respostas:       list[RespostaItem]

class RespostaQuestaoOut(OrmBase):
    questao_id:          uuid.UUID
    alternativa_id:      uuid.UUID | None
    correta:             bool
    tempo_resposta_seg:  int | None
    alternativa_correta: AlternativaComGabaritoOut | None = None

class TentativaOut(OrmBase):
    id:              uuid.UUID
    quiz_id:         uuid.UUID
    pontuacao:       int
    acertos:         int
    total_questoes:  int
    tempo_gasto_seg: int | None
    realizado_em:    datetime
    respostas:       list[RespostaQuestaoOut] = []


# ── Melhor tentativa por quiz ─────────────────────────────────────────────────

class MelhorTentativaOut(BaseModel):
    quiz_id:        uuid.UUID
    pontuacao:      int   # 0-100
    acertos:        int
    total_questoes: int
    aprovado:       bool  # pontuacao >= 75


# ── Progresso ────────────────────────────────────────────────────────────────

class ProgressoOut(OrmBase):
    topico_id:    uuid.UUID
    status:       StatusProgresso
    pontuacao:    int
    iniciado_em:  datetime | None = None
    concluido_em: datetime | None = None


# ── Recomendação ─────────────────────────────────────────────────────────────

class RecomendacaoOut(OrmBase):
    id:               uuid.UUID
    topico_id:        uuid.UUID
    score_relevancia: float
    motivo:           str | None
    visualizada:      bool
    gerada_em:        datetime
    topico:           TopicoOut | None = None


# ── Dashboard ────────────────────────────────────────────────────────────────

class DashboardAlunoOut(BaseModel):
    usuario:          UsuarioOut
    pontuacao_geral:  float
    taxa_acerto_pct:  float
    total_exercicios: int
    sequencia_dias:   int
    progressos:       list[ProgressoOut]
    recomendacoes:    list[RecomendacaoOut]

class AlunoResumoOut(BaseModel):
    usuario:          UsuarioOut
    pontuacao_media:  float
    taxa_acerto_pct:  float
    total_tentativas: int
    ultimo_acesso:    datetime | None

class DashboardProfessorOut(BaseModel):
    media_turma:    float
    total_alunos:   int
    alunos_ativos:  int
    precisam_apoio: int
    alunos:         list[AlunoResumoOut]