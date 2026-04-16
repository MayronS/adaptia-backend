from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone


from app.database import get_db
from app.models.models import Usuario, UsuarioPerfil, PerfilUsuario
from app.schemas.schemas import (
    LoginRequest, Token, UsuarioCreate, UsuarioOut,
    AdicionarPerfilRequest,
)
from app.services.auth_service import (
    hash_password, verify_password, create_access_token, get_current_user,
)

router = APIRouter(prefix="/auth", tags=["autenticação"])

ADMIN_SUFFIX = "/admin"


def _carregar_usuario_com_perfis(query):
    """Helper para sempre carregar a relação 'perfis' junto com o usuário."""
    return query.options(selectinload(Usuario.perfis))


@router.post("/login", response_model=Token)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Autentica o usuário e retorna um JWT.

    - Se o usuário tiver apenas um perfil, ele é usado automaticamente.
    - Se tiver múltiplos perfis, informe o campo `perfil` no body para
      selecionar qual sessão abrir (ex: "aluno" ou "professor").
    - Login de administrador: use o e-mail com sufixo /admin.
    """
    email_raw  = body.email.strip()
    is_admin   = email_raw.endswith(ADMIN_SUFFIX)
    email_real = email_raw[: -len(ADMIN_SUFFIX)] if is_admin else email_raw

    res  = await db.execute(
        _carregar_usuario_com_perfis(select(Usuario).where(Usuario.email == email_real))
    )
    user = res.scalar_one_or_none()

    if not user or not verify_password(body.password, user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
        )

    if not user.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta desativada")

    perfis_ativos = user.get_perfis_ativos()

    # Login com /admin: exige perfil admin
    if is_admin:
        if PerfilUsuario.admin not in perfis_ativos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta conta não tem permissão de administrador",
            )
        perfil_sessao = PerfilUsuario.admin

    else:
        if not perfis_ativos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nenhum perfil ativo encontrado para esta conta",
            )

        if len(perfis_ativos) == 1:
            # Apenas um perfil: usa automaticamente
            perfil_sessao = perfis_ativos[0]
        else:
            # Múltiplos perfis: exige que o cliente informe qual usar
            if body.perfil is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": "Este usuário possui múltiplos perfis. Informe o campo 'perfil' para selecionar.",
                        "perfis_disponiveis": [p.value for p in perfis_ativos],
                    },
                )
            if body.perfil not in perfis_ativos:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Perfil '{body.perfil.value}' não encontrado nesta conta",
                )
            perfil_sessao = body.perfil

    user.ultimo_acesso = datetime.now(timezone.utc)
    token = create_access_token(user.id, perfil_sessao)

    return Token(
        access_token=token,
        perfis=perfis_ativos,
    )


@router.post("/register", response_model=UsuarioOut, status_code=201)
async def register(body: UsuarioCreate, db: AsyncSession = Depends(get_db)):
    """
    Cria um novo usuário ou adiciona um perfil a uma conta existente.

    - Se o e-mail NÃO existir: cria o usuário com o perfil informado.
    - Se o e-mail JÁ existir e o perfil for diferente: adiciona o novo perfil
      à conta existente (exige a mesma senha para confirmar identidade).
    - Se o e-mail e perfil já existirem: retorna erro 409.
    - Perfil 'admin' não pode ser criado por esta rota.
    """
    if body.perfil == PerfilUsuario.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil administrador não pode ser criado por esta rota",
        )

    res = await db.execute(
        _carregar_usuario_com_perfis(select(Usuario).where(Usuario.email == body.email))
    )
    existing = res.scalar_one_or_none()

    if existing:
        # E-mail já cadastrado — tenta adicionar novo perfil
        if not verify_password(body.password, existing.senha_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Senha incorreta para este e-mail",
            )
        if existing.tem_perfil(body.perfil):
            raise HTTPException(
                status_code=409,
                detail=f"Este e-mail já possui o perfil '{body.perfil.value}'",
            )
        # Adiciona o novo perfil
        novo_perfil = UsuarioPerfil(usuario_id=existing.id, perfil=body.perfil)
        db.add(novo_perfil)
        await db.flush()

        await db.commit()
        await db.refresh(existing)
        return UsuarioOut.from_usuario(existing)

    # Novo usuário
    user = Usuario(
        nome=body.nome,
        email=body.email,
        senha_hash=hash_password(body.password),
        palavra_chave_hash=hash_password(body.palavra_chave) if body.palavra_chave else None,
        palavra_chave_dica=body.palavra_chave_dica or None,
    )
    db.add(user)
    await db.flush()  # gera o ID

    perfil_obj = UsuarioPerfil(usuario_id=user.id, perfil=body.perfil)
    db.add(perfil_obj)

    await db.commit()
    await db.refresh(user, ["perfis"])
    return UsuarioOut.from_usuario(user)



@router.post("/adicionar-perfil", response_model=UsuarioOut)
async def adicionar_perfil(
    body: AdicionarPerfilRequest,
    db:   AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """
    Adiciona um novo perfil ao usuário autenticado.
    Útil para usuários que já estão logados e querem ativar o perfil professor (ou aluno).
    """
    if body.perfil == PerfilUsuario.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil administrador não pode ser adicionado por esta rota",
        )

    # Recarrega com perfis
    res = await db.execute(
        _carregar_usuario_com_perfis(select(Usuario).where(Usuario.id == user.id))
    )
    user = res.scalar_one()

    if user.tem_perfil(body.perfil):
        raise HTTPException(
            status_code=409,
            detail=f"Você já possui o perfil '{body.perfil.value}'",
        )

    novo_perfil = UsuarioPerfil(usuario_id=user.id, perfil=body.perfil)
    db.add(novo_perfil)

    await db.commit()
    await db.refresh(user, ["perfis"])
    return UsuarioOut.from_usuario(user)

@router.get("/me", response_model=UsuarioOut)
async def me(
    user: Usuario = Depends(get_current_user),
):
    """Retorna os dados do usuário autenticado."""
    return UsuarioOut.from_usuario(user)

@router.post("/alterar-senha", status_code=200)
async def alterar_senha(
    body: dict,
    user: Usuario      = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    """Altera a senha do usuário autenticado. Exige a senha atual para confirmar."""
    senha_atual = body.get("senha_atual", "")
    nova_senha  = body.get("nova_senha", "")

    if not senha_atual or not nova_senha:
        raise HTTPException(status_code=422, detail="Senha atual e nova senha são obrigatórias")

    if len(nova_senha) < 6:
        raise HTTPException(status_code=422, detail="A nova senha deve ter pelo menos 6 caracteres")

    if not verify_password(senha_atual, user.senha_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")

    if senha_atual == nova_senha:
        raise HTTPException(status_code=400, detail="A nova senha deve ser diferente da atual")

    user.senha_hash = hash_password(nova_senha)
    await db.commit()

    return {"mensagem": "Senha alterada com sucesso"}

@router.post("/recuperar-senha", status_code=200)
async def recuperar_senha(
    body: dict,
    db:   AsyncSession = Depends(get_db),
):
    """Recupera acesso redefinindo a senha via nome + e-mail + palavra-chave."""
    nome         = (body.get("nome") or "").strip()
    email        = (body.get("email") or "").strip().lower()
    palavra_chave = (body.get("palavra_chave") or "").strip()
    nova_senha   = (body.get("nova_senha") or "").strip()

    if not all([nome, email, palavra_chave, nova_senha]):
        raise HTTPException(status_code=422, detail="Todos os campos são obrigatórios")

    if len(nova_senha) < 6:
        raise HTTPException(status_code=422, detail="A nova senha deve ter pelo menos 6 caracteres")

    res = await db.execute(
        _carregar_usuario_com_perfis(select(Usuario).where(Usuario.email == email))
    )
    user = res.scalar_one_or_none()

    # Mesma mensagem para não revelar se e-mail existe
    erro_generico = HTTPException(status_code=400, detail="Dados incorretos. Verifique nome, e-mail e palavra-chave.")

    if not user:
        raise erro_generico

    # Verifica nome (case-insensitive)
    if user.nome.strip().lower() != nome.lower():
        raise erro_generico

    # Verifica palavra-chave
    if not user.palavra_chave_hash or not verify_password(palavra_chave, user.palavra_chave_hash):
        raise erro_generico

    user.senha_hash = hash_password(nova_senha)
    await db.commit()

    return {"mensagem": "Senha redefinida com sucesso! Faça login com sua nova senha."}


@router.post("/palavra-chave", response_model=UsuarioOut, status_code=200)
async def salvar_palavra_chave(
    body: dict,
    user: Usuario      = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    """Cria ou edita a palavra-chave de recuperação e sua dica."""
    palavra_chave = (body.get("palavra_chave") or "").strip()
    dica          = (body.get("dica") or "").strip()

    if not palavra_chave:
        raise HTTPException(status_code=422, detail="A palavra-chave não pode ser vazia")

    if len(palavra_chave) < 3:
        raise HTTPException(status_code=422, detail="A palavra-chave deve ter pelo menos 3 caracteres")

    if len(dica) > 200:
        raise HTTPException(status_code=422, detail="A dica deve ter no máximo 200 caracteres")

    user.palavra_chave_hash = hash_password(palavra_chave)
    user.palavra_chave_dica = dica if dica else None

    await db.commit()
    await db.refresh(user, ["perfis"])
    return UsuarioOut.from_usuario(user)

@router.get("/palavra-chave-dica", status_code=200)
async def obter_dica_palavra_chave(
    email: str,
    db:    AsyncSession = Depends(get_db),
):
    """Retorna a dica da palavra-chave para um e-mail (sem autenticação)."""
    res = await db.execute(
        select(Usuario).where(Usuario.email == email.strip().lower())
    )
    user = res.scalar_one_or_none()

    # Não revela se o e-mail existe ou não
    if not user or not user.palavra_chave_hash:
        return {"dica": None}

    return {"dica": user.palavra_chave_dica}