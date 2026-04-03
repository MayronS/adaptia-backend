import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    String, Text, Boolean, Integer, SmallInteger,
    ForeignKey, Numeric, Enum as SAEnum, TIMESTAMP,
    UniqueConstraint, CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


# ── Enums ────────────────────────────────────────────────────────────────────

class PerfilUsuario(str, enum.Enum):
    aluno      = "aluno"
    professor  = "professor"
    admin      = "admin"

class StatusProgresso(str, enum.Enum):
    bloqueado    = "bloqueado"
    disponivel   = "disponivel"
    em_progresso = "em_progresso"
    concluido    = "concluido"

class TipoQuestao(str, enum.Enum):
    multipla_escolha = "multipla_escolha"
    verdadeiro_falso = "verdadeiro_falso"
    dissertativa     = "dissertativa"


# ── Tabelas ──────────────────────────────────────────────────────────────────

class Usuario(Base):
    __tablename__ = "usuarios"

    id:            Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome:          Mapped[str]             = mapped_column(String(120), nullable=False)
    email:         Mapped[str]             = mapped_column(String(180), nullable=False, unique=True)
    senha_hash:    Mapped[str]             = mapped_column(Text, nullable=False)
    ativo:         Mapped[bool]            = mapped_column(Boolean, nullable=False, default=True)
    criado_em:     Mapped[datetime]        = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Perfis do usuário (pode ter aluno, professor, ou ambos)
    perfis:        Mapped[list["UsuarioPerfil"]]       = relationship(back_populates="usuario", cascade="all, delete-orphan")
    progressos:    Mapped[list["ProgressoTopico"]]     = relationship(back_populates="usuario", cascade="all, delete-orphan")
    tentativas:    Mapped[list["TentativaQuiz"]]       = relationship(back_populates="usuario", cascade="all, delete-orphan")
    recomendacoes: Mapped[list["Recomendacao"]]        = relationship(back_populates="usuario", cascade="all, delete-orphan")

    def tem_perfil(self, perfil: PerfilUsuario) -> bool:
        """Verifica se o usuário possui um determinado perfil ativo."""
        return any(p.perfil == perfil and p.ativo for p in self.perfis)

    def get_perfis_ativos(self) -> list[PerfilUsuario]:
        """Retorna lista de perfis ativos do usuário."""
        return [p.perfil for p in self.perfis if p.ativo]


class UsuarioPerfil(Base):
    """
    Tabela de vínculo entre usuário e perfis.
    Um mesmo usuário pode ser aluno e professor simultaneamente.
    """
    __tablename__ = "usuario_perfis"
    __table_args__ = (
        UniqueConstraint("usuario_id", "perfil", name="uq_usuario_perfil"),
    )

    id:         Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID]     = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    perfil:     Mapped[PerfilUsuario] = mapped_column(SAEnum(PerfilUsuario, name="perfil_usuario"), nullable=False)
    ativo:      Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True)
    criado_em:  Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    usuario: Mapped["Usuario"] = relationship(back_populates="perfis")


class Materia(Base):
    __tablename__ = "materias"

    id:        Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome:      Mapped[str]        = mapped_column(String(80), nullable=False, unique=True)
    descricao: Mapped[str | None] = mapped_column(Text)
    icone:     Mapped[str | None] = mapped_column(String(10))
    cor:       Mapped[str | None] = mapped_column(String(7))
    ordem:     Mapped[int]        = mapped_column(SmallInteger, nullable=False, default=0)
    ativo:     Mapped[bool]       = mapped_column(Boolean, nullable=False, default=True)

    topicos: Mapped[list["Topico"]] = relationship(back_populates="materia", cascade="all, delete-orphan")


class Topico(Base):
    __tablename__ = "topicos"

    id:                Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    materia_id:        Mapped[uuid.UUID]      = mapped_column(ForeignKey("materias.id", ondelete="CASCADE"), nullable=False)
    titulo:            Mapped[str]            = mapped_column(String(120), nullable=False)
    descricao:         Mapped[str | None]     = mapped_column(Text)
    ordem:             Mapped[int]            = mapped_column(SmallInteger, nullable=False, default=0)
    nivel_dificuldade: Mapped[int]            = mapped_column(SmallInteger, nullable=False, default=1)
    prerequisito_id:   Mapped[uuid.UUID|None] = mapped_column(ForeignKey("topicos.id", ondelete="SET NULL"), nullable=True)
    ativo:             Mapped[bool]           = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("nivel_dificuldade BETWEEN 1 AND 5", name="ck_topico_nivel"),
    )

    materia:       Mapped["Materia"]               = relationship(back_populates="topicos")
    prerequisito:  Mapped["Topico | None"]         = relationship("Topico", remote_side="Topico.id")
    quizzes:       Mapped[list["Quiz"]]            = relationship(back_populates="topico", cascade="all, delete-orphan")
    progressos:    Mapped[list["ProgressoTopico"]] = relationship(back_populates="topico", cascade="all, delete-orphan")
    recomendacoes: Mapped[list["Recomendacao"]]    = relationship(back_populates="topico", cascade="all, delete-orphan")


class Quiz(Base):
    __tablename__ = "quizzes"

    id:               Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topico_id:        Mapped[uuid.UUID]  = mapped_column(ForeignKey("topicos.id", ondelete="CASCADE"), nullable=False)
    titulo:           Mapped[str]        = mapped_column(String(120), nullable=False)
    descricao:        Mapped[str | None] = mapped_column(Text)
    tempo_limite_seg: Mapped[int | None] = mapped_column(Integer)
    pontuacao_maxima: Mapped[int]        = mapped_column(Integer, nullable=False, default=100)
    tentativas_max:   Mapped[int | None] = mapped_column(SmallInteger)
    ativo:            Mapped[bool]       = mapped_column(Boolean, nullable=False, default=True)
    criado_em:        Mapped[datetime]   = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    topico:     Mapped["Topico"]              = relationship(back_populates="quizzes")
    questoes:   Mapped[list["Questao"]]       = relationship(back_populates="quiz", cascade="all, delete-orphan")
    tentativas: Mapped[list["TentativaQuiz"]] = relationship(back_populates="quiz", cascade="all, delete-orphan")


class Questao(Base):
    __tablename__ = "questoes"

    id:        Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id:   Mapped[uuid.UUID]   = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    enunciado: Mapped[str]         = mapped_column(Text, nullable=False)
    tipo:      Mapped[TipoQuestao] = mapped_column(SAEnum(TipoQuestao, name="tipo_questao"), nullable=False, default=TipoQuestao.multipla_escolha)
    pontos:        Mapped[int]  = mapped_column(SmallInteger, nullable=False, default=1)
    ordem:         Mapped[int]  = mapped_column(SmallInteger, nullable=False, default=0)
    ativo:         Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    total_acertos: Mapped[int]  = mapped_column(Integer, nullable=False, default=0)
    total_erros:   Mapped[int]  = mapped_column(Integer, nullable=False, default=0)

    quiz:         Mapped["Quiz"]                  = relationship(back_populates="questoes")
    alternativas: Mapped[list["Alternativa"]]     = relationship(back_populates="questao", cascade="all, delete-orphan")
    respostas:    Mapped[list["RespostaQuestao"]] = relationship(back_populates="questao")


class Alternativa(Base):
    __tablename__ = "alternativas"

    id:         Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    questao_id: Mapped[uuid.UUID]  = mapped_column(ForeignKey("questoes.id", ondelete="CASCADE"), nullable=False)
    texto:      Mapped[str]        = mapped_column(Text, nullable=False)
    correta:    Mapped[bool]       = mapped_column(Boolean, nullable=False, default=False)
    explicacao: Mapped[str | None] = mapped_column(Text)
    ordem:      Mapped[int]        = mapped_column(SmallInteger, nullable=False, default=0)

    questao:   Mapped["Questao"]               = relationship(back_populates="alternativas")
    respostas: Mapped[list["RespostaQuestao"]] = relationship(back_populates="alternativa")


class ProgressoTopico(Base):
    __tablename__ = "progresso_topicos"
    __table_args__ = (UniqueConstraint("usuario_id", "topico_id"),)

    id:           Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id:   Mapped[uuid.UUID]       = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    topico_id:    Mapped[uuid.UUID]       = mapped_column(ForeignKey("topicos.id",  ondelete="CASCADE"), nullable=False)
    status:       Mapped[StatusProgresso] = mapped_column(SAEnum(StatusProgresso, name="status_progresso"), nullable=False, default=StatusProgresso.bloqueado)
    pontuacao:    Mapped[int]             = mapped_column(SmallInteger, nullable=False, default=0)
    iniciado_em:  Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    concluido_em: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    usuario: Mapped["Usuario"] = relationship(back_populates="progressos")
    topico:  Mapped["Topico"]  = relationship(back_populates="progressos")


class TentativaQuiz(Base):
    __tablename__ = "tentativas_quiz"

    id:              Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id:      Mapped[uuid.UUID]  = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    quiz_id:         Mapped[uuid.UUID]  = mapped_column(ForeignKey("quizzes.id",  ondelete="CASCADE"), nullable=False)
    pontuacao:       Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    acertos:         Mapped[int]        = mapped_column(SmallInteger, nullable=False, default=0)
    total_questoes:  Mapped[int]        = mapped_column(SmallInteger, nullable=False, default=0)
    tempo_gasto_seg: Mapped[int | None] = mapped_column(Integer)
    realizado_em:    Mapped[datetime]   = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    usuario:   Mapped["Usuario"]               = relationship(back_populates="tentativas")
    quiz:      Mapped["Quiz"]                  = relationship(back_populates="tentativas")
    respostas: Mapped[list["RespostaQuestao"]] = relationship(back_populates="tentativa", cascade="all, delete-orphan")


class RespostaQuestao(Base):
    __tablename__ = "respostas_questoes"
    __table_args__ = (UniqueConstraint("tentativa_id", "questao_id"),)

    id:                 Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tentativa_id:       Mapped[uuid.UUID]      = mapped_column(ForeignKey("tentativas_quiz.id", ondelete="CASCADE"), nullable=False)
    questao_id:         Mapped[uuid.UUID]      = mapped_column(ForeignKey("questoes.id",        ondelete="CASCADE"), nullable=False)
    alternativa_id:     Mapped[uuid.UUID|None] = mapped_column(ForeignKey("alternativas.id",    ondelete="SET NULL"), nullable=True)
    resposta_texto:     Mapped[str | None]     = mapped_column(Text)
    correta:            Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)
    tempo_resposta_seg: Mapped[int | None]     = mapped_column(SmallInteger)

    tentativa:   Mapped["TentativaQuiz"]      = relationship(back_populates="respostas")
    questao:     Mapped["Questao"]            = relationship(back_populates="respostas")
    alternativa: Mapped["Alternativa | None"] = relationship(back_populates="respostas")


class Recomendacao(Base):
    __tablename__ = "recomendacoes"

    id:               Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id:       Mapped[uuid.UUID]  = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    topico_id:        Mapped[uuid.UUID]  = mapped_column(ForeignKey("topicos.id",  ondelete="CASCADE"), nullable=False)
    score_relevancia: Mapped[float]      = mapped_column(Numeric(5, 4), nullable=False, default=0)
    motivo:           Mapped[str | None] = mapped_column(String(120))
    visualizada:      Mapped[bool]       = mapped_column(Boolean, nullable=False, default=False)
    gerada_em:        Mapped[datetime]   = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    usuario: Mapped["Usuario"] = relationship(back_populates="recomendacoes")
    topico:  Mapped["Topico"]  = relationship(back_populates="recomendacoes")
