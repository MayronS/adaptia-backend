from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator, model_validator
from app.models.models import PerfilUsuario, StatusProgresso, TipoQuestao


# ── Helpers ──────────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email:    str   # aceita "email@x.com" ou "email@x.com/admin"
    password: str
    # Perfil desejado para o login (quando o usuário tem múltiplos perfis)
    perfil:   PerfilUsuario | None = None

    @field_validator("email")
    @classmethod
    def validar_email(cls, v: str) -> str:
        v = v.strip()
        # Remove sufixo /admin para validar só a parte do email
        email_puro = v.removesuffix("/admin")
        # Validação básica de formato
        if "@" not in email_puro or "." not in email_puro.split("@")[-1]:
            raise ValueError("E-mail inválido")
        return v

class Token(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    perfis:       list[PerfilUsuario] = []  # todos os perfis ativos do usuário

class TokenData(BaseModel):
    usuario_id:    uuid.UUID
    perfil_ativo:  PerfilUsuario  # perfil com o qual o usuário fez login nesta sessão


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
    perfis:        list[PerfilUsuario] = []  # lista de todos os perfis ativos
    ativo:         bool
    criado_em:     datetime
    ultimo_acesso: datetime | None = None

    @classmethod
    def from_usuario(cls, u: object) -> "UsuarioOut":
        """Constrói UsuarioOut a partir de um objeto Usuario ORM."""
        return cls(
            id=u.id,
            nome=u.nome,
            email=u.email,
            perfis=u.get_perfis_ativos(),
            ativo=u.ativo,
            criado_em=u.criado_em,
            ultimo_acesso=u.ultimo_acesso,
        )


# ── Adicionar perfil ─────────────────────────────────────────────────────────

class AdicionarPerfilRequest(BaseModel):
    """Permite que um usuário já autenticado adicione um novo perfil à sua conta."""
    perfil: PerfilUsuario


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
    tentativas_max:         int | None
    questoes_por_tentativa: int | None = None
    ativo:                  bool

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
    pass

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
    pontuacao:      int
    acertos:        int
    total_questoes: int
    aprovado:       bool


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


# ── Admin: Create schemas ─────────────────────────────────────────────────────

class MateriaCreate(BaseModel):
    nome:      str           = Field(..., min_length=2, max_length=80)
    descricao: str | None    = None
    icone:     str | None    = Field(None, max_length=10)
    cor:       str | None    = Field(None, max_length=7)
    ordem:     int           = 0
    ativo:     bool          = True

class TopicoCreate(BaseModel):
    titulo:            str           = Field(..., min_length=2, max_length=120)
    descricao:         str | None    = None
    ordem:             int           = 0
    nivel_dificuldade: int           = Field(1, ge=1, le=5)
    prerequisito_id:   uuid.UUID | None = None
    ativo:             bool          = True

class QuizCreate(BaseModel):
    titulo:           str           = Field(..., min_length=2, max_length=120)
    descricao:        str | None    = None
    tempo_limite_seg: int | None    = None
    pontuacao_maxima: int           = 100
    tentativas_max:         int | None = None
    questoes_por_tentativa: int | None = Field(default=None, description='Quantas questões sortear por tentativa. None = todas.')
    ativo:                  bool       = True

class AlternativaCreate(BaseModel):
    texto:      str            = Field(..., min_length=1)
    correta:    bool           = False
    explicacao: str | None     = None

class QuestaoCreate(BaseModel):
    enunciado:    str                  = Field(..., min_length=5)
    tipo:         TipoQuestao          = TipoQuestao.multipla_escolha
    pontos:       int                  = Field(1, ge=1)
    alternativas: list[AlternativaCreate] = Field(default_factory=list)


# ── Vínculos Professor-Aluno ──────────────────────────────────────────────────

from app.models.models import StatusVinculo

class ConviteCreate(BaseModel):
    aluno_email: EmailStr

class ConviteOut(BaseModel):
    id:            uuid.UUID
    status:        StatusVinculo
    criado_em:     datetime
    respondido_em: datetime | None = None
    professor:     UsuarioOut | None = None
    aluno:         UsuarioOut | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def converter_usuarios(cls, data):
        """Converte objetos Usuario ORM para UsuarioOut usando from_usuario()."""
        # Quando vem do ORM (objeto), acessa atributos diretamente
        if hasattr(data, "__class__") and not isinstance(data, dict):
            prof = getattr(data, "professor", None)
            alun = getattr(data, "aluno", None)
            return {
                "id":             data.id,
                "status":         data.status,
                "criado_em":      data.criado_em,
                "respondido_em":  getattr(data, "respondido_em", None),
                "professor":      UsuarioOut.from_usuario(prof) if prof else None,
                "aluno":          UsuarioOut.from_usuario(alun) if alun else None,
            }
        return data

class ResponderConviteRequest(BaseModel):
    aceitar: bool


# ══════════════════════════════════════════════════════════════════════════════
# TURMAS
# ══════════════════════════════════════════════════════════════════════════════

class TurmaCreate(BaseModel):
    nome:      str          = Field(..., min_length=2, max_length=120)
    descricao: str | None   = None

class TurmaAlternativaOut(OrmBase):
    id:         uuid.UUID
    texto:      str
    correta:    bool
    explicacao: str | None = None
    ordem:      int

class TurmaAlternativaCreate(BaseModel):
    texto:      str        = Field(..., min_length=1)
    correta:    bool       = False
    explicacao: str | None = None

class TurmaQuestaoOut(OrmBase):
    id:           uuid.UUID
    enunciado:    str
    tipo:         TipoQuestao
    pontos:       int
    ordem:        int
    alternativas: list[TurmaAlternativaOut] = []

class TurmaQuestaoCreate(BaseModel):
    enunciado:    str                       = Field(..., min_length=5)
    tipo:         TipoQuestao               = TipoQuestao.multipla_escolha
    pontos:       int                       = Field(1, ge=1)
    alternativas: list[TurmaAlternativaCreate] = Field(default_factory=list)

class TurmaQuizOut(OrmBase):
    id:               uuid.UUID
    turma_id:         uuid.UUID
    titulo:           str
    descricao:        str | None
    tempo_limite_seg: int | None
    ativo:            bool
    criado_em:        datetime
    questoes:         list[TurmaQuestaoOut] = []

class TurmaQuizCreate(BaseModel):
    titulo:           str          = Field(..., min_length=2, max_length=120)
    descricao:        str | None   = None
    tempo_limite_seg: int | None   = None
    ativo:            bool         = True

class TurmaAlunoOut(OrmBase):
    id:        uuid.UUID
    aluno_id:  uuid.UUID
    criado_em: datetime
    aluno:     UsuarioOut | None = None

    @model_validator(mode="before")
    @classmethod
    def conv(cls, data):
        if hasattr(data, "__class__") and not isinstance(data, dict):
            aluno = getattr(data, "aluno", None)
            return {
                "id":        data.id,
                "aluno_id":  data.aluno_id,
                "criado_em": data.criado_em,
                "aluno":     UsuarioOut.from_usuario(aluno) if aluno else None,
            }
        return data

class TurmaOut(OrmBase):
    id:         uuid.UUID
    nome:       str
    descricao:  str | None
    ativo:      bool
    criado_em:  datetime
    professor:  UsuarioOut | None = None
    alunos:     list[TurmaAlunoOut] = []
    quizzes:    list[TurmaQuizOut]  = []

    @model_validator(mode="before")
    @classmethod
    def conv_professor(cls, data):
        if hasattr(data, "__class__") and not isinstance(data, dict):
            prof = getattr(data, "professor", None)
            return {
                "id":         data.id,
                "nome":       data.nome,
                "descricao":  getattr(data, "descricao", None),
                "ativo":      data.ativo,
                "criado_em":  data.criado_em,
                "professor":  UsuarioOut.from_usuario(prof) if prof else None,
                "alunos":     getattr(data, "alunos", []),
                "quizzes":    getattr(data, "quizzes", []),
            }
        return data

class TurmaRespostaItem(BaseModel):
    questao_id:     uuid.UUID
    alternativa_id: uuid.UUID | None = None

class TentativaTurmaCreate(BaseModel):
    quiz_id:         uuid.UUID
    tempo_gasto_seg: int | None = None
    respostas:       list[TurmaRespostaItem]

class TentativaTurmaOut(OrmBase):
    id:              uuid.UUID
    quiz_id:         uuid.UUID
    pontuacao:       int
    acertos:         int
    total_questoes:  int
    tempo_gasto_seg: int | None
    realizado_em:    datetime
