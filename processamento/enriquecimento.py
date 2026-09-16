"""Validação, normalização e classificação para o módulo de
enriquecimento de empresas e contatos.

Este módulo só processa achados de pesquisa que já foram coletados (por
um agente humano/IA usando ferramentas de busca fora deste código) — ele
mesmo NUNCA acessa a internet. Isso mantém a lógica de negócio (o que é
um e-mail válido, que cargo é prioridade 1, etc.) testável sem rede e
sem risco de fazer alguma chamada indevida.

LGPD: este módulo só deve receber dados profissionais/institucionais já
tornados públicos pela própria empresa (site, redes oficiais). Não faz
nenhuma validação de "é pessoal ou profissional" sozinho — isso é
responsabilidade de quem pesquisa (ver docs/decisoes.md)."""
from __future__ import annotations

import re
import unicodedata

NIVEIS_CONFIANCA = {"ALTO", "MEDIO", "BAIXO", "NAO_CONFIRMADO"}

TIPOS_PRESENCA_DIGITAL = {"site", "linkedin", "instagram", "facebook", "youtube", "outro"}

CATEGORIAS_EVIDENCIA = {
    "ESG",
    "SUSTENTABILIDADE",
    "RESPONSABILIDADE_SOCIAL",
    "INSTITUTO",
    "FUNDACAO",
    "PATROCINIO",
    "MARKETING",
    "COMUNICACAO",
    "RELACOES_INSTITUCIONAIS",
    "FISCAL",
    "TRIBUTARIO",
    "CONTABILIDADE",
    "OUTRO",
}

# Categorias que indicam abertura institucional para parcerias sociais
# (usadas no Contactability Score e na Prioridade de Prospecção).
CATEGORIAS_RELEVANCIA_IORM = {"ESG", "SUSTENTABILIDADE", "RESPONSABILIDADE_SOCIAL", "INSTITUTO", "FUNDACAO"}

# Palavras-chave (sem acento, minúsculas) usadas para classificar
# cargo/departamento em prioridade de contato. Baseadas só no texto
# publicamente disponível — nunca inferindo responsabilidade não escrita.
_PALAVRAS_PRIORIDADE_1 = [
    "esg",
    "sustentabilidade",
    "responsabilidade social",
    "instituto",
    "fundacao",
    "investimento social",
    "relacoes institucionais",
    "patrocinio",
]
_PALAVRAS_PRIORIDADE_2 = [
    "marketing",
    "comunicacao",
    "relacoes publicas",
    "diretoria",
    "presidencia",
]
_PALAVRAS_PRIORIDADE_3 = [
    "recursos humanos",
    " rh",
    "rh ",
    "fiscal",
    "tributario",
    "contabilidade",
    "controladoria",
]


def _remover_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def classificar_prioridade(cargo_ou_departamento: str | None) -> str | None:
    """Classifica um cargo/departamento em PRIORIDADE_1/2/3. Devolve None
    se não reconhecer nenhuma palavra-chave (não adivinha)."""
    if not cargo_ou_departamento:
        return None
    texto = f" {_remover_acentos(cargo_ou_departamento.lower())} "
    if any(p in texto for p in _PALAVRAS_PRIORIDADE_1):
        return "PRIORIDADE_1"
    if any(p in texto for p in _PALAVRAS_PRIORIDADE_2):
        return "PRIORIDADE_2"
    if any(p in texto for p in _PALAVRAS_PRIORIDADE_3):
        return "PRIORIDADE_3"
    return None


def normalizar_email(email: str | None) -> str | None:
    if not email:
        return None
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return None
    return email


def normalizar_telefone(telefone: str | None) -> str | None:
    """Mantém só dígitos (com + inicial se o original tinha). Devolve
    None se sobrarem poucos dígitos para parecer um telefone de verdade."""
    if not telefone:
        return None
    tem_mais = telefone.strip().startswith("+")
    digitos = re.sub(r"\D", "", telefone)
    if len(digitos) < 10:
        return None
    return f"+{digitos}" if tem_mais else digitos


def normalizar_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    return url.rstrip("/")


def normalizar_nome_pessoa(nome: str | None) -> str | None:
    if not nome:
        return None
    return " ".join(nome.strip().split()).title()


def validar_nivel_confianca(nivel: str) -> str:
    if nivel not in NIVEIS_CONFIANCA:
        raise ValueError(f"Nível de confiança inválido: {nivel!r}. Use um de {sorted(NIVEIS_CONFIANCA)}.")
    return nivel


def validar_tipo_presenca_digital(tipo: str) -> str:
    tipo = (tipo or "").strip().lower()
    if tipo not in TIPOS_PRESENCA_DIGITAL:
        raise ValueError(f"Tipo de presença digital inválido: {tipo!r}.")
    return tipo


def validar_categoria_evidencia(categoria: str) -> str:
    categoria = (categoria or "").strip().upper()
    if categoria not in CATEGORIAS_EVIDENCIA:
        raise ValueError(f"Categoria de evidência inválida: {categoria!r}.")
    return categoria
