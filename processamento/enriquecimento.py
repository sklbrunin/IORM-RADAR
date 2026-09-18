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
    "captacao de recursos",
    "captacao",
]
_PALAVRAS_PRIORIDADE_2 = [
    "marketing",
    "comunicacao",
    "relacoes publicas",
    "diretoria",
    "diretor",
    "presidencia",
    "presidente",
    "relacoes com investidores",
    "investidores",
]
_PALAVRAS_PRIORIDADE_3 = [
    "recursos humanos",
    " rh",
    "rh ",
    "fiscal",
    "tributario",
    "contabilidade",
    "contabil",
    "controladoria",
    "controller",
    "juridico",
    "jurídico",
]

# Áreas oficiais do sistema (rótulo exibido) e as palavras-chave, sem acento,
# que a identificam num cargo/departamento OU no início de um e-mail
# institucional. Ordem = precedência (a mais específica primeiro).
AREAS_PROFISSIONAIS: list[tuple[str, list[str]]] = [
    ("Responsabilidade Social", ["responsabilidade social", "responsabilidadesocial", "rsc", "social"]),
    ("ESG", ["esg"]),
    ("Sustentabilidade", ["sustentabilidade", "sustentavel", "meio ambiente", "ambiental"]),
    ("Instituto/Fundação", ["instituto", "fundacao", "investimento social"]),
    ("Captação/Patrocínios", ["captacao", "patrocinio", "patrocinios", "incentivo"]),
    ("Relações Institucionais", ["relacoes institucionais", "institucional", "relacoes publicas", "relacionamento"]),
    ("Relações com Investidores", ["relacoes com investidores", "investidores", "ri"]),
    ("Marketing", ["marketing", "mkt"]),
    ("Comunicação", ["comunicacao", "imprensa", "assessoria"]),
    ("Fiscal", ["fiscal"]),
    ("Tributário", ["tributario", "tributos", "impostos"]),
    ("Contabilidade", ["contabilidade", "contabil", "contador"]),
    ("Controladoria", ["controladoria", "controller"]),
    ("Jurídico", ["juridico", "legal", "advogado"]),
    ("RH", ["recursos humanos", "rh", "pessoas", "curriculo", "gente e gestao"]),
    ("Diretoria", ["diretoria", "diretor", "presidencia", "presidente", "ceo"]),
    ("Financeiro", ["financeiro", "tesouraria"]),
    ("Comercial", ["comercial", "vendas"]),
    ("Atendimento/Geral", ["atendimento", "contato", "faleconosco", "sac", "ouvidoria", "geral", "info", "secretaria"]),
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


def classificar_area(texto: str | None) -> str | None:
    """Área profissional (rótulo de AREAS_PROFISSIONAIS) citada num cargo ou
    departamento. Só reconhece palavra que está escrita — sem palavra, None."""
    if not texto:
        return None
    limpo = _remover_acentos(texto.lower())
    palavras = set(re.findall(r"[a-z0-9]+", limpo))
    for rotulo, chaves in AREAS_PROFISSIONAIS:
        for chave in chaves:
            if (" " in chave and chave in limpo) or chave in palavras:
                return rotulo
    return None


def area_do_email(email: str | None) -> str | None:
    """Área de um e-mail INSTITUCIONAL a partir da parte antes do "@"
    (ex: financeiro@ -> Financeiro). Isso descreve o setor da caixa
    postal — nunca identifica uma pessoa. Sem correspondência, None."""
    email = normalizar_email(email)
    if not email:
        return None
    parte = _remover_acentos(email.split("@", 1)[0])
    palavras = set(re.findall(r"[a-z0-9]+", parte))
    juntas = re.sub(r"[^a-z0-9]", "", parte)
    for rotulo, chaves in AREAS_PROFISSIONAIS:
        for chave in chaves:
            chave_junta = chave.replace(" ", "")
            if chave in palavras or (len(chave_junta) >= 5 and chave_junta in juntas):
                return rotulo
    return None


def parece_email_de_pessoa(email: str | None) -> bool:
    """Heurística conservadora: nome.sobrenome@ ou inicial+sobrenome sugere
    caixa pessoal. Serve para NUNCA rotular um e-mail como "do responsável"
    sem evidência — a tela só o chama de pessoal quando há nome+cargo na fonte."""
    email = normalizar_email(email)
    if not email or area_do_email(email):
        return False
    parte = email.split("@", 1)[0]
    return bool(re.fullmatch(r"[a-z]{2,}[._-][a-z]{2,}", parte))


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
