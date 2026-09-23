"""Descoberta nacional de empresas (v9).

Encontra empresas NOVAS em qualquer estado do Brasil, por provedores plugáveis (mesmo desenho de SearchProvider /
ContactProvider / IncentivoProvider). A Região IORM é PRIORIDADE, não restrição: a busca vai do mais perto para o mais longe.

    Nível 1  cidades de atuação do IORM (Cérebro da OSC)
    Nível 2  estado(s) de atuação (SP)
    Nível 3  demais estados
    Nível 4  Brasil inteiro (sem filtro geográfico)

Regras que este módulo garante (todas com teste):
  * Descoberta ≠ relacionamento: nada aqui marca `relacionamento_iorm`. Empresa já existente (inclusive Linha Cruzada) nunca
    volta como "nova": recebe só uma nova ORIGEM.
  * Empresa sem CNPJ entra como CANDIDATA (`estagio_cadastro`), fora da contagem de prospects e da fila de enriquecimento até a
    equipe validar. Nenhum CNPJ é inventado; CNPJ inválido é descartado.
  * Deduplicação em ordem: CNPJ → domínio/site → id externo → nome+cidade+UF → parecido (só SINALIZA "possível duplicata",
    nunca funde nem apaga).
  * Proveniência: cada empresa guarda TODAS as origens (`empresas_origens`), sem sobrescrever dado existente.
  * Créditos: cada chamada gera um evento em `uso_api_eventos`; provedor sem cota fica "sem cota" e os demais continuam.
  * Provedor sem credencial/plano NUNCA é dado como funcionando: aparece como "sem credencial" e é pulado.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

from processamento import banco, fila_enriquecimento, validadores

# ------------------------------------------------------------------ configuração (variáveis de ambiente, sem chaves no código)
EMPRESAS_NOVAS_POR_DIA_PADRAO = 50
LIMITE_POR_PROVIDER_PADRAO = 25       # empresas NOVAS por provedor por execução
MAX_CHAMADAS_POR_PROVIDER_PADRAO = 40  # chamadas (páginas) por provedor por execução; os níveis 3/4 percorrem ~26 estados

UFS_EXPANSAO = ["SP", "MG", "PR", "RJ", "MT", "GO"] + sorted(validadores.UFS_VALIDAS - {"SP", "MG", "PR", "RJ", "MT", "GO"})
NOME_ESTADO = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}
_UF_POR_NOME = {re.sub(r"\W", "", unicodedata.normalize("NFD", n.lower())): uf for uf, n in NOME_ESTADO.items()}

STATUS_DISPONIVEL, STATUS_SEM_CREDENCIAL, STATUS_SEM_COTA = "DISPONIVEL", "SEM_CREDENCIAL", "SEM_COTA"
STATUS_INDISPONIVEL, STATUS_DESABILITADO, STATUS_ERRO, STATUS_CONCLUIDO = "INDISPONIVEL", "DESABILITADO", "ERRO", "CONCLUIDO"

RES_NOVA_CONFIRMADA, RES_NOVA_CANDIDATA, RES_EXISTENTE = "NOVA_CONFIRMADA", "NOVA_CANDIDATA", "EXISTENTE"
RES_POSSIVEL_DUPLICATA, RES_REJEITADA = "POSSIVEL_DUPLICATA", "REJEITADA"

ESTAGIO_CONFIRMADA, ESTAGIO_CANDIDATA = "CONFIRMADA", "CANDIDATA"
LIMIAR_PARECIDO = 0.92


def empresas_novas_por_dia() -> int:
    try:
        return max(0, int(os.environ.get("EMPRESAS_NOVAS_POR_DIA", EMPRESAS_NOVAS_POR_DIA_PADRAO)))
    except ValueError:
        return EMPRESAS_NOVAS_POR_DIA_PADRAO


def _inteiro_env(nome: str, padrao: int) -> int:
    try:
        return max(0, int(os.environ[nome]))
    except (KeyError, ValueError):
        return padrao


def limite_por_provider(nome: str) -> int:
    """`LIMITE_POR_PROVIDER_<NOME>` tem prioridade sobre `LIMITE_POR_PROVIDER`."""
    return _inteiro_env(f"LIMITE_POR_PROVIDER_{nome.upper()}", _inteiro_env("LIMITE_POR_PROVIDER", LIMITE_POR_PROVIDER_PADRAO))


def max_chamadas_por_provider() -> int:
    return _inteiro_env("DESCOBERTA_MAX_CHAMADAS", MAX_CHAMADAS_POR_PROVIDER_PADRAO)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ normalização
def remover_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


_FORMAS_JURIDICAS = {"ltda", "sa", "me", "epp", "eireli", "mei", "ss"}


def normalizar_nome(nome) -> str:
    texto = remover_acentos(str(nome or "").lower())
    texto = re.sub(r"\bs\s*[./]\s*a\b\.?", " sa ", texto)
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return " ".join(t for t in texto.split() if t not in _FORMAS_JURIDICAS)


def normalizar_local(valor) -> str:
    return re.sub(r"[^a-z0-9]+", " ", remover_acentos(str(valor or "").lower())).strip()


def normalizar_uf(valor) -> str | None:
    if not valor:
        return None
    uf = validadores.validar_uf(valor)
    if uf:
        return uf
    return _UF_POR_NOME.get(re.sub(r"\W", "", unicodedata.normalize("NFD", str(valor).lower())))


_HOSPEDAGENS_GENERICAS = {"facebook.com", "instagram.com", "linkedin.com", "google.com", "youtube.com", "twitter.com", "x.com",
                          "wa.me", "linktr.ee", "wixsite.com", "blogspot.com", "gmail.com", "hotmail.com", "outlook.com",
                          "yahoo.com", "yahoo.com.br", "bol.com.br", "uol.com.br", "tiktok.com", "whatsapp.com"}


def normalizar_dominio(valor) -> str | None:
    """Domínio próprio da empresa (sem www/caminho). Redes sociais e provedores de e-mail não identificam a empresa: None."""
    texto = str(valor or "").strip().lower()
    if not texto:
        return None
    if "@" in texto and "/" not in texto:
        texto = texto.split("@", 1)[1]
    if "://" not in texto:
        texto = "http://" + texto
    host = (urlparse(texto).hostname or "").removeprefix("www.")
    if "." not in host or host in _HOSPEDAGENS_GENERICAS or any(host.endswith("." + g) for g in _HOSPEDAGENS_GENERICAS):
        return None
    return host


# ------------------------------------------------------------------ tipos
@dataclass
class EmpresaDescoberta:
    nome: str
    cnpj: str | None = None
    nome_fantasia: str | None = None
    site: str | None = None
    cidade: str | None = None
    estado: str | None = None
    setor: str | None = None
    id_externo: str | None = None
    url_fonte: str | None = None
    incentivo: dict | None = None  # só o SALIC traz (doação real com URL de fonte)
    bruto: dict = field(default_factory=dict)


@dataclass
class Consulta:
    nivel: int
    uf: str | None = None
    cidade: str | None = None
    setor: str | None = None
    tema: str | None = None
    porte: str | None = None
    limite: int = 25
    cursor: dict = field(default_factory=dict)

    def chave(self, provider: str) -> str:
        return ":".join([provider, str(self.nivel), self.uf or "", normalizar_local(self.cidade), self.setor or ""])


@dataclass
class ResultadoBusca:
    empresas: list[EmpresaDescoberta]
    chamadas: int = 1
    creditos: float = 0.0
    esgotado: bool = False       # não há mais páginas para esta consulta
    proximo_cursor: dict = field(default_factory=dict)


class ProvedorSemCredencial(Exception):
    """Falta chave/credencial — ou a chave existe mas o plano não dá acesso à API."""


class ProvedorSemCota(Exception):
    """Créditos/limite do plano esgotados (ou limite de taxa)."""


class ProvedorIndisponivel(Exception):
    """Serviço fora do ar, resposta inesperada ou formato não reconhecido."""


# ------------------------------------------------------------------ contrato dos provedores
class CompanyDiscoveryProvider(ABC):
    nome: str = ""               # chave estável (grava em uso_api / origens)
    rotulo: str = ""
    capacidade: str = ""
    custo: str = ""
    acesso: str = ""             # como o app chega ao serviço (API REST / API pública)
    variaveis_credencial: tuple[str, ...] = ()
    niveis_suportados: tuple[int, ...] = (1, 2, 3, 4)
    habilitado_por_padrao: bool = True
    validado_em_producao: bool = False   # True só quando houve chamada real bem-sucedida documentada
    observacao_validacao: str = ""

    def __init__(self, http=None):
        import requests

        self._http = http or requests.request

    def credencial_configurada(self) -> bool:
        return all(os.environ.get(v) for v in self.variaveis_credencial) if self.variaveis_credencial else True

    def limite_mensal(self) -> int | None:
        """Teto mensal de consumo definido pela equipe (`DESCOBERTA_LIMITE_MENSAL_<NOME>`); None = sem teto próprio."""
        valor = os.environ.get(f"DESCOBERTA_LIMITE_MENSAL_{self.nome.upper()}")
        return int(valor) if valor and valor.isdigit() else None

    def orcamento(self, conexao: sqlite3.Connection) -> int | None:
        limite = self.limite_mensal()
        if limite is None:
            return None
        return max(0, limite - fila_enriquecimento.uso_mes(conexao, self.nome))

    def status(self, conexao: sqlite3.Connection | None = None) -> dict:
        if not self.credencial_configurada():
            faltam = [v for v in self.variaveis_credencial if not os.environ.get(v)]
            return {"estado": STATUS_SEM_CREDENCIAL, "motivo": f"Defina no .env: {', '.join(faltam)}."}
        if conexao is not None:
            orcamento = self.orcamento(conexao)
            if orcamento is not None and orcamento <= 0:
                return {"estado": STATUS_SEM_COTA, "motivo": "O teto mensal configurado para este provedor foi atingido."}
        return {"estado": STATUS_DISPONIVEL, "motivo": ""}

    @abstractmethod
    def buscar(self, consulta: Consulta) -> ResultadoBusca:
        """Uma chamada (uma página). Levanta ProvedorSemCredencial / ProvedorSemCota / ProvedorIndisponivel."""

    # utilitário comum: traduz o HTTP em exceções do contrato
    def _checar_http(self, resposta) -> None:
        codigo = resposta.status_code
        if codigo in (401, 403):
            raise ProvedorSemCredencial(f"HTTP {codigo}: chave recusada ou plano sem acesso à API de busca de empresas.")
        if codigo in (402, 429):
            raise ProvedorSemCota(f"HTTP {codigo}: créditos ou limite de taxa esgotados.")
        if codigo >= 400:
            raise ProvedorIndisponivel(f"HTTP {codigo} inesperado.")


def _localizacao_texto(consulta: Consulta) -> str:
    partes = [consulta.cidade, NOME_ESTADO.get(consulta.uf or "")]
    return ", ".join([p for p in partes if p] + ["Brazil"])


# ------------------------------------------------------------------ provedores
class SalicDiscoveryProvider(CompanyDiscoveryProvider):
    """API pública do SALIC (Lei Rouanet): incentivadores pessoa jurídica por UF. Traz CNPJ e doações reais com URL de fonte.
    Gratuita e sem credencial. Por UF (níveis 2 e 3): não filtra por cidade."""

    nome = "SALIC"
    rotulo = "SALIC (Lei Rouanet)"
    capacidade = "Empresas incentivadoras da Lei Rouanet, por estado, com CNPJ e histórico de doações."
    custo = "Gratuito"
    acesso = "API pública do Ministério da Cultura"
    niveis_suportados = (2, 3)
    validado_em_producao = True
    observacao_validacao = "Integração real já usada pela coleta diária desde a v5."

    def buscar(self, consulta: Consulta) -> ResultadoBusca:
        from coleta import coleta_salic
        from processamento import transformacao

        uf = consulta.uf
        offset = int(consulta.cursor.get("offset", 0))
        limite = max(1, min(coleta_salic.LIMITE_POR_PAGINA, consulta.limite))
        try:
            resposta = self._http("GET", coleta_salic.BASE_URL, params={"UF": uf, "tipo_pessoa": "juridica", "limit": limite, "offset": offset},
                                  timeout=30)
            resposta.raise_for_status()
            carga = resposta.json()
        except Exception as erro:  # rede/HTTP/JSON
            raise ProvedorIndisponivel(f"SALIC indisponível: {erro}") from erro
        registros = carga.get("_embedded", {}).get("incentivadores", [])
        empresas = []
        for bruto in registros:
            transformado = transformacao.transformar_registro(bruto, fonte_nome=coleta_salic.FONTE_NOME)
            if transformado is None:
                continue
            e = transformado["empresa"]
            empresas.append(EmpresaDescoberta(
                nome=e["razao_social"], cnpj=e.get("cnpj"), nome_fantasia=e.get("nome_fantasia"), cidade=e.get("cidade"),
                estado=e.get("estado"), id_externo=e.get("cnpj"), url_fonte=transformado["incentivo"].get("url_fonte"),
                incentivo=transformado["incentivo"]))
        total = carga.get("total")
        novo_offset = offset + len(registros)
        esgotado = not registros or (total is not None and novo_offset >= total)
        return ResultadoBusca(empresas, chamadas=1, creditos=0, esgotado=esgotado, proximo_cursor={"offset": novo_offset})


class SerpApiMapsDiscoveryProvider(CompanyDiscoveryProvider):
    """Google Maps via SerpApi: negócios por cidade/estado. Sem CNPJ (entram como CANDIDATAS). Consome a MESMA cota de buscas
    da SerpApi usada pelo enriquecimento, por isso vem DESLIGADO por padrão e respeita a reserva para uso manual."""

    nome = "SerpApi"
    rotulo = "SerpApi — Google Maps"
    capacidade = "Negócios locais por cidade/estado (nome, endereço, site). Não traz CNPJ."
    custo = "1 busca da cota mensal da SerpApi por chamada (cota compartilhada com o enriquecimento)"
    acesso = "API REST (SerpApi)"
    variaveis_credencial = ("SERPAPI_API_KEY",)
    niveis_suportados = (1, 2, 3)
    habilitado_por_padrao = False
    validado_em_producao = True
    observacao_validacao = ("Validado em 23/09/2026 com UMA chamada real (Orlândia/SP: 20 empresas, cidade e UF lidas do endereço). "
                            "Ainda não usado na rotina diária (vem desligado).")
    _URL = "https://serpapi.com/search"

    def orcamento(self, conexao):
        return fila_enriquecimento.orcamento_serpapi(conexao)

    def buscar(self, consulta: Consulta) -> ResultadoBusca:
        termo = consulta.setor or consulta.tema or "empresas"
        local = ", ".join(p for p in [consulta.cidade, NOME_ESTADO.get(consulta.uf or "")] if p) or "Brasil"
        parametros = {"engine": "google_maps", "type": "search", "q": f"{termo} em {local}", "hl": "pt-br", "gl": "br",
                      "start": int(consulta.cursor.get("start", 0)), "api_key": os.environ.get("SERPAPI_API_KEY", "")}
        try:
            resposta = self._http("GET", self._URL, params=parametros, timeout=30)
        except Exception as erro:
            raise ProvedorIndisponivel(f"SerpApi indisponível: {erro}") from erro
        self._checar_http(resposta)
        try:
            carga = resposta.json()
        except ValueError as erro:
            raise ProvedorIndisponivel("Resposta da SerpApi não é JSON.") from erro
        erro_api = str(carga.get("error") or "")
        if "hasn't returned any results" in erro_api.lower():
            return ResultadoBusca([], chamadas=1, creditos=1, esgotado=True)
        if erro_api:
            raise ProvedorIndisponivel(f"SerpApi: {erro_api}")
        empresas = []
        for item in carga.get("local_results") or []:
            nome = item.get("title")
            if not nome:
                continue
            cidade, uf = _cidade_uf_do_endereco(item.get("address"), consulta)
            empresas.append(EmpresaDescoberta(nome=nome, site=item.get("website"), cidade=cidade, estado=uf, setor=item.get("type"),
                                              id_externo=str(item.get("place_id") or item.get("data_id") or "") or None,
                                              url_fonte=item.get("website"), bruto={"endereco": item.get("address")}))
        return ResultadoBusca(empresas, chamadas=1, creditos=1, esgotado=len(empresas) < 20,
                              proximo_cursor={"start": int(consulta.cursor.get("start", 0)) + 20})


def _cidade_uf_do_endereco(endereco, consulta: Consulta) -> tuple[str | None, str | None]:
    """Só devolve cidade/UF quando o próprio endereço do provedor traz ("... - Guaíra - SP"). Nada é deduzido da consulta."""
    if not endereco:
        return None, None
    m = re.search(r"([^,\-]+?)\s*-\s*([A-Z]{2})\b", str(endereco))
    if m and validadores.validar_uf(m.group(2)):
        return m.group(1).strip(), m.group(2)
    return None, None


class ApolloDiscoveryProvider(CompanyDiscoveryProvider):
    """Apollo.io — Organization Search (POST /api/v1/mixed_companies/search). A documentação oficial informa que o endpoint só está
    disponível em planos pagos (403 no plano gratuito) e consome 1 crédito por página."""

    nome = "Apollo"
    rotulo = "Apollo.io"
    capacidade = "Empresas por localização/palavra-chave, com domínio e site (sem CNPJ)."
    custo = "Créditos Apollo (1 por página); exige plano pago para a API"
    acesso = "API REST (chave própria — o conector do Claude NÃO é acessível pelo app)"
    variaveis_credencial = ("APOLLO_API_KEY",)
    observacao_validacao = "Formato conforme docs.apollo.io; não validado com chave real neste ambiente."
    _URL = "https://api.apollo.io/api/v1/mixed_companies/search"

    def buscar(self, consulta: Consulta) -> ResultadoBusca:
        pagina = int(consulta.cursor.get("page", 1))
        corpo = {"page": pagina, "per_page": max(1, min(100, consulta.limite)),
                 "organization_locations": [_localizacao_texto(consulta)]}
        if consulta.setor or consulta.tema:
            corpo["q_organization_keyword_tags"] = [consulta.setor or consulta.tema]
        try:
            resposta = self._http("POST", self._URL, json=corpo, timeout=30,
                                  headers={"x-api-key": os.environ.get("APOLLO_API_KEY", ""), "Content-Type": "application/json"})
        except Exception as erro:
            raise ProvedorIndisponivel(f"Apollo indisponível: {erro}") from erro
        self._checar_http(resposta)
        try:
            carga = resposta.json()
        except ValueError as erro:
            raise ProvedorIndisponivel("Resposta do Apollo não é JSON.") from erro
        organizacoes = carga.get("organizations") or carga.get("accounts") or []
        empresas = []
        for o in organizacoes:
            if not o.get("name"):
                continue
            empresas.append(EmpresaDescoberta(
                nome=o["name"], site=o.get("website_url") or o.get("primary_domain"), cidade=o.get("city"), estado=normalizar_uf(o.get("state")),
                id_externo=str(o["id"]) if o.get("id") else None, url_fonte=o.get("linkedin_url") or o.get("website_url"),
                setor=o.get("industry")))
        paginacao = carga.get("pagination") or {}
        esgotado = not organizacoes or (paginacao.get("total_pages") is not None and pagina >= int(paginacao["total_pages"]))
        return ResultadoBusca(empresas, chamadas=1, creditos=1, esgotado=esgotado, proximo_cursor={"page": pagina + 1})


class LushaDiscoveryProvider(CompanyDiscoveryProvider):
    """Lusha — Prospecting Company Search (POST https://api.lusha.com/prospecting/company/search, cabeçalho api_key)."""

    nome = "Lusha"
    rotulo = "Lusha"
    capacidade = "Empresas por localização (país/estado/cidade), com domínio (sem CNPJ)."
    custo = "Créditos Lusha (1 crédito por 25 empresas listadas); limites diário/horário do plano"
    acesso = "API REST (chave própria — o conector do Claude NÃO é acessível pelo app)"
    variaveis_credencial = ("LUSHA_API_KEY",)
    observacao_validacao = ("Corpo da requisição montado a partir da documentação/esquema públicos do Lusha; formato da resposta lido de "
                            "forma tolerante. NÃO validado com chave real neste ambiente.")
    _URL = "https://api.lusha.com/prospecting/company/search"

    def buscar(self, consulta: Consulta) -> ResultadoBusca:
        pagina = int(consulta.cursor.get("page", 0))
        local = {"country": "Brazil"}
        if consulta.uf:
            local["state"] = NOME_ESTADO.get(consulta.uf, consulta.uf)
        if consulta.cidade:
            local["city"] = consulta.cidade
        corpo = {"pages": {"page": pagina, "size": max(10, min(50, consulta.limite))},
                 "filters": {"companies": {"include": {"locations": [local]}}}}
        try:
            resposta = self._http("POST", self._URL, json=corpo, timeout=30,
                                  headers={"api_key": os.environ.get("LUSHA_API_KEY", ""), "Content-Type": "application/json"})
        except Exception as erro:
            raise ProvedorIndisponivel(f"Lusha indisponível: {erro}") from erro
        self._checar_http(resposta)
        try:
            carga = resposta.json()
        except ValueError as erro:
            raise ProvedorIndisponivel("Resposta do Lusha não é JSON.") from erro
        linhas = carga.get("data") or carga.get("companies") or carga.get("results") or []
        if isinstance(linhas, dict):
            linhas = linhas.get("companies") or linhas.get("results") or []
        empresas = []
        for c in linhas:
            nome = c.get("name") or c.get("companyName")
            if not nome:
                continue
            loc = c.get("location") or c.get("mainLocation") or {}
            empresas.append(EmpresaDescoberta(
                nome=nome, site=c.get("domain") or c.get("fqdn") or c.get("website"), cidade=loc.get("city"),
                estado=normalizar_uf(loc.get("state")), id_externo=str(c.get("id") or c.get("companyId") or "") or None,
                url_fonte=c.get("website") or c.get("linkedinUrl")))
        creditos = max(1, -(-len(linhas) // 25)) if linhas else 0
        return ResultadoBusca(empresas, chamadas=1, creditos=creditos, esgotado=len(linhas) < consulta.limite,
                              proximo_cursor={"page": pagina + 1})


class SnovDiscoveryProvider(CompanyDiscoveryProvider):
    """Snov.io — Database search companies (POST /v2/database-search/companies/start; OAuth client credentials). No plano gratuito
    a API entrega 1 página. O fluxo é assíncrono; se a resposta não trouxer o resultado em formato reconhecido, o provedor se declara
    indisponível em vez de inventar dados."""

    nome = "Snov"
    rotulo = "Snov.io"
    capacidade = "Empresas por localização/setor (busca no banco do Snov.io), com domínio (sem CNPJ)."
    custo = "Créditos Snov.io (1 por consulta com resultado); plano gratuito limitado a 1 página"
    acesso = "API REST com OAuth (chave própria — o conector do Claude NÃO é acessível pelo app)"
    variaveis_credencial = ("SNOV_CLIENT_ID", "SNOV_CLIENT_SECRET")
    niveis_suportados = (2, 3, 4)
    observacao_validacao = ("Autenticação e endpoint conforme a documentação pública; fluxo assíncrono de resultados NÃO validado com "
                            "credenciais reais neste ambiente.")
    _URL_TOKEN = "https://api.snov.io/v1/oauth/access_token"
    _URL_BUSCA = "https://api.snov.io/v2/database-search/companies/start"

    def _token(self) -> str:
        try:
            r = self._http("POST", self._URL_TOKEN, timeout=30, data={
                "grant_type": "client_credentials", "client_id": os.environ.get("SNOV_CLIENT_ID", ""),
                "client_secret": os.environ.get("SNOV_CLIENT_SECRET", "")})
        except Exception as erro:
            raise ProvedorIndisponivel(f"Snov indisponível: {erro}") from erro
        self._checar_http(r)
        token = (r.json() or {}).get("access_token")
        if not token:
            raise ProvedorSemCredencial("O Snov.io não devolveu access_token para as credenciais informadas.")
        return token

    def buscar(self, consulta: Consulta) -> ResultadoBusca:
        token = self._token()
        local = {"name": NOME_ESTADO.get(consulta.uf, "Brazil") if consulta.uf else "Brazil"}
        corpo = {"filter": {"company_locations": {"include": [local]}}, "page": int(consulta.cursor.get("page", 1))}
        try:
            r = self._http("POST", self._URL_BUSCA, json=corpo, timeout=60, headers={"Authorization": f"Bearer {token}"})
        except Exception as erro:
            raise ProvedorIndisponivel(f"Snov indisponível: {erro}") from erro
        self._checar_http(r)
        try:
            carga = r.json()
        except ValueError as erro:
            raise ProvedorIndisponivel("Resposta do Snov.io não é JSON.") from erro
        linhas = carga.get("companies") or carga.get("data") or carga.get("results")
        if not isinstance(linhas, list):
            raise ProvedorIndisponivel("O Snov.io respondeu no fluxo assíncrono, cujo formato de resultado não está validado aqui.")
        empresas = []
        for c in linhas:
            nome = c.get("name") or c.get("company_name")
            if nome:
                empresas.append(EmpresaDescoberta(
                    nome=nome, site=c.get("domain") or c.get("website"), cidade=c.get("city") or c.get("locality"),
                    estado=normalizar_uf(c.get("state")), id_externo=str(c.get("id") or "") or None, setor=c.get("industry")))
        return ResultadoBusca(empresas, chamadas=1, creditos=1 if linhas else 0, esgotado=len(linhas) < consulta.limite,
                              proximo_cursor={"page": int(consulta.cursor.get("page", 1)) + 1})


def providers_padrao(http=None) -> list[CompanyDiscoveryProvider]:
    return [SalicDiscoveryProvider(http), SerpApiMapsDiscoveryProvider(http), ApolloDiscoveryProvider(http),
            LushaDiscoveryProvider(http), SnovDiscoveryProvider(http)]


# ------------------------------------------------------------------ banco
def criar_tabelas(conexao: sqlite3.Connection) -> None:
    """Idempotente: nunca apaga nem altera dado existente. Empresas antigas ficam CONFIRMADA (default)."""
    banco.criar_tabelas(conexao)
    banco.migrar_empresas(conexao)
    fila_enriquecimento.criar_tabelas(conexao)
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS empresas_origens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL REFERENCES empresas(id),
            provider TEXT NOT NULL,
            id_externo TEXT,
            nome_no_provider TEXT,
            dominio TEXT,
            url_fonte TEXT,
            nivel INTEGER,
            uf_consulta TEXT,
            resultado TEXT,
            payload_json TEXT,
            descoberto_em TEXT NOT NULL,
            UNIQUE (empresa_id, provider, id_externo)
        );
        CREATE INDEX IF NOT EXISTS idx_origens_externo ON empresas_origens (provider, id_externo);
        CREATE INDEX IF NOT EXISTS idx_origens_dominio ON empresas_origens (dominio);
        CREATE TABLE IF NOT EXISTS descoberta_execucoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iniciado_em TEXT NOT NULL, finalizado_em TEXT, origem TEXT, meta INTEGER,
            status TEXT, resumo_json TEXT
        );
        CREATE TABLE IF NOT EXISTS descoberta_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execucao_id INTEGER NOT NULL REFERENCES descoberta_execucoes(id),
            provider TEXT NOT NULL, status TEXT NOT NULL, chamadas INTEGER NOT NULL DEFAULT 0, creditos REAL NOT NULL DEFAULT 0,
            encontradas INTEGER NOT NULL DEFAULT 0, novas_confirmadas INTEGER NOT NULL DEFAULT 0, novas_candidatas INTEGER NOT NULL DEFAULT 0,
            existentes INTEGER NOT NULL DEFAULT 0, possiveis_duplicatas INTEGER NOT NULL DEFAULT 0, rejeitadas INTEGER NOT NULL DEFAULT 0,
            detalhe TEXT
        );
        CREATE TABLE IF NOT EXISTS descoberta_estado (
            chave TEXT PRIMARY KEY, cursor_json TEXT NOT NULL, concluido INTEGER NOT NULL DEFAULT 0, atualizado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS descoberta_providers (
            provider TEXT PRIMARY KEY, habilitado INTEGER NOT NULL, atualizado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS uso_api_eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL, data TEXT NOT NULL, operacao TEXT NOT NULL, quantidade INTEGER NOT NULL DEFAULT 0,
            creditos REAL NOT NULL DEFAULT 0, sucesso INTEGER NOT NULL, empresa_id INTEGER, detalhe TEXT, criado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rotina_etapas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL, etapa TEXT NOT NULL, status TEXT NOT NULL, iniciado_em TEXT, finalizado_em TEXT,
            detalhe TEXT, resumo_json TEXT, UNIQUE (data, etapa)
        );
        """
    )
    atuais = {l[1] for l in conexao.execute("PRAGMA table_info(empresas)")}
    for coluna, definicao in {"dominio": "TEXT", "estagio_cadastro": f"TEXT NOT NULL DEFAULT '{ESTAGIO_CONFIRMADA}'",
                              "possivel_duplicata_de": "INTEGER", "origem_descoberta": "TEXT"}.items():
        if coluna not in atuais:
            conexao.execute(f"ALTER TABLE empresas ADD COLUMN {coluna} {definicao}")
    conexao.commit()


def provider_habilitado(conexao: sqlite3.Connection, provider: CompanyDiscoveryProvider) -> bool:
    linha = conexao.execute("SELECT habilitado FROM descoberta_providers WHERE provider = ?", (provider.nome,)).fetchone()
    return bool(linha[0]) if linha else provider.habilitado_por_padrao


def definir_habilitado(conexao: sqlite3.Connection, nome: str, habilitado: bool) -> None:
    conexao.execute(
        """INSERT INTO descoberta_providers (provider, habilitado, atualizado_em) VALUES (?, ?, ?)
           ON CONFLICT (provider) DO UPDATE SET habilitado = excluded.habilitado, atualizado_em = excluded.atualizado_em""",
        (nome, int(habilitado), _agora().isoformat()))
    conexao.commit()


def registrar_evento(conexao: sqlite3.Connection, provider: str, operacao: str, quantidade: int = 0, creditos: float = 0,
                     sucesso: bool = True, empresa_id: int | None = None, detalhe: str | None = None) -> None:
    agora = _agora()
    conexao.execute(
        """INSERT INTO uso_api_eventos (provider, data, operacao, quantidade, creditos, sucesso, empresa_id, detalhe, criado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (provider, agora.strftime("%Y-%m-%d"), operacao, quantidade, creditos, int(sucesso), empresa_id, detalhe, agora.isoformat()))
    conexao.commit()


def creditos_do_mes(conexao: sqlite3.Connection, provider: str) -> float:
    mes = _agora().strftime("%Y-%m")
    linha = conexao.execute("SELECT COALESCE(SUM(creditos), 0) FROM uso_api_eventos WHERE provider = ? AND data LIKE ? AND sucesso = 1",
                            (provider, f"{mes}%")).fetchone()
    return float(linha[0])


# ------------------------------------------------------------------ deduplicação
class IndiceDedupe:
    """Índice em memória das empresas existentes para a ordem: CNPJ → domínio → id externo → nome+local → parecido."""

    def __init__(self, conexao: sqlite3.Connection):
        self.por_cnpj: dict[str, int] = {}
        self.por_dominio: dict[str, int] = {}
        self.por_externo: dict[tuple[str, str], int] = {}
        self.por_nome_local: dict[tuple[str, str, str], int] = {}
        self.por_uf: dict[str, list[tuple[int, str]]] = {}
        self.cnpj_de: dict[int, str | None] = {}
        cnpj_col = conexao.execute("SELECT id, cnpj, razao_social, nome_fantasia, cidade, estado, dominio FROM empresas").fetchall()
        for id_, cnpj, razao, fantasia, cidade, estado, dominio in cnpj_col:
            self.cnpj_de[id_] = cnpj
            self._indexar(id_, cnpj, [razao, fantasia], cidade, estado, dominio)
        for id_, url in conexao.execute("SELECT empresa_id, url FROM presenca_digital WHERE LOWER(tipo) IN ('site', 'website')") \
                if _tabela_existe(conexao, "presenca_digital") else []:
            d = normalizar_dominio(url)
            if d:
                self.por_dominio.setdefault(d, id_)
        for id_, prov, ext, dom in conexao.execute("SELECT empresa_id, provider, id_externo, dominio FROM empresas_origens"):
            if ext:
                self.por_externo[(prov, ext)] = id_
            if dom:
                self.por_dominio.setdefault(dom, id_)

    def _indexar(self, id_, cnpj, nomes, cidade, estado, dominio) -> None:
        if cnpj:
            self.por_cnpj[cnpj] = id_
        if dominio:
            self.por_dominio.setdefault(dominio, id_)
        uf = normalizar_uf(estado) or ""
        for nome in nomes:
            n = normalizar_nome(nome)
            if not n:
                continue
            if cidade and uf:
                self.por_nome_local.setdefault((n, normalizar_local(cidade), uf), id_)
            self.por_uf.setdefault(uf, []).append((id_, n))

    def adicionar(self, id_: int, item: EmpresaDescoberta, provider: str, cnpj: str | None) -> None:
        self.cnpj_de[id_] = cnpj
        self._indexar(id_, cnpj, [item.nome, item.nome_fantasia], item.cidade, item.estado, normalizar_dominio(item.site))
        if item.id_externo:
            self.por_externo[(provider, item.id_externo)] = id_

    def localizar(self, item: EmpresaDescoberta, provider: str, cnpj: str | None) -> tuple[str, int] | None:
        """(critério, empresa_id) do primeiro critério EXATO que casa; None se nenhum."""
        candidatos: list[tuple[str, int | None]] = [
            ("CNPJ", self.por_cnpj.get(cnpj) if cnpj else None),
            ("DOMINIO", self.por_dominio.get(normalizar_dominio(item.site) or "")),
            ("ID_EXTERNO", self.por_externo.get((provider, item.id_externo)) if item.id_externo else None),
        ]
        uf = normalizar_uf(item.estado) or ""
        if item.cidade and uf:
            for nome in (item.nome, item.nome_fantasia):
                n = normalizar_nome(nome)
                if n:
                    candidatos.append(("NOME_LOCAL", self.por_nome_local.get((n, normalizar_local(item.cidade), uf))))
        for criterio, id_ in candidatos:
            if id_ is None:
                continue
            # dois CNPJs diferentes = duas empresas distintas: um critério mais fraco nunca pode fundi-las
            existente_cnpj = self.cnpj_de.get(id_)
            if cnpj and existente_cnpj and cnpj != existente_cnpj:
                continue
            return criterio, id_
        return None

    def parecido(self, item: EmpresaDescoberta) -> int | None:
        """Empresa de nome muito parecido no mesmo estado — só para SINALIZAR possível duplicata."""
        uf = normalizar_uf(item.estado)
        if not uf:
            return None
        n = normalizar_nome(item.nome)
        if len(n) < 6:
            return None
        melhor, melhor_id = 0.0, None
        for id_, outro in self.por_uf.get(uf, []):
            if abs(len(outro) - len(n)) > 8:
                continue
            razao = SequenceMatcher(None, n, outro).ratio()
            if razao > melhor:
                melhor, melhor_id = razao, id_
        return melhor_id if melhor >= LIMIAR_PARECIDO else None


def _tabela_existe(conexao: sqlite3.Connection, nome: str) -> bool:
    return conexao.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (nome,)).fetchone() is not None


def _registrar_origem(conexao, empresa_id: int, item: EmpresaDescoberta, provider: str, consulta: Consulta | None, resultado: str) -> None:
    conexao.execute(
        """INSERT OR IGNORE INTO empresas_origens
           (empresa_id, provider, id_externo, nome_no_provider, dominio, url_fonte, nivel, uf_consulta, resultado, payload_json, descoberto_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (empresa_id, provider, item.id_externo or f"sem-id:{normalizar_nome(item.nome)}:{normalizar_local(item.cidade)}:{normalizar_uf(item.estado) or ''}",
         item.nome, normalizar_dominio(item.site), item.url_fonte,
         consulta.nivel if consulta else None, consulta.uf if consulta else None, resultado,
         json.dumps({"setor": item.setor, "cidade": item.cidade, "estado": item.estado, "cnpj_informado": bool(item.cnpj), **item.bruto},
                    ensure_ascii=False, default=str), _agora().isoformat()))


def _completar_vazios(conexao, empresa_id: int, item: EmpresaDescoberta) -> None:
    """Só PREENCHE campos vazios da empresa existente; nunca sobrescreve o que já está lá."""
    atual = conexao.execute("SELECT cidade, estado, dominio FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    novos = {}
    if not atual[0] and item.cidade:
        novos["cidade"] = item.cidade
    if not atual[1] and normalizar_uf(item.estado):
        novos["estado"] = normalizar_uf(item.estado)
    if not atual[2] and normalizar_dominio(item.site):
        novos["dominio"] = normalizar_dominio(item.site)
    if novos:
        conexao.execute(f"UPDATE empresas SET {', '.join(f'{k} = ?' for k in novos)} WHERE id = ?", (*novos.values(), empresa_id))


def _incentivo_ja_registrado(conexao: sqlite3.Connection, empresa_id: int, incentivo: dict) -> bool:
    """A URL da SALIC muda a cada consulta (o hash do link não é estável), então a URL sozinha NÃO identifica um incentivo:
    a mesma empresa relida apareceria de novo com outro link e o valor doado seria contado em dobro. Mesma empresa + mesma
    fonte + mesmo tipo + mesmo valor/projeto/ano = o mesmo incentivo."""
    return conexao.execute(
        """SELECT 1 FROM incentivos WHERE empresa_id = ? AND fonte = ? AND tipo_incentivo = ? AND COALESCE(valor, -1) = COALESCE(?, -1)
             AND COALESCE(projeto, '') = COALESCE(?, '') AND COALESCE(ano, 0) = COALESCE(?, 0) LIMIT 1""",
        (empresa_id, incentivo.get("fonte"), incentivo.get("tipo_incentivo"), incentivo.get("valor"), incentivo.get("projeto"),
         incentivo.get("ano"))).fetchone() is not None


def _gravar_incentivo(conexao: sqlite3.Connection, empresa_id: int, incentivo: dict | None) -> None:
    if incentivo and not _incentivo_ja_registrado(conexao, empresa_id, incentivo):
        banco.inserir_ou_atualizar_incentivo(conexao, {**incentivo, "empresa_id": empresa_id})


def ingerir(conexao: sqlite3.Connection, item: EmpresaDescoberta, provider: str, indice: IndiceDedupe,
            consulta: Consulta | None = None) -> dict:
    """Aplica UMA empresa descoberta. Devolve {"resultado": RES_*, "empresa_id": int|None, "criterio": str|None}."""
    nome = (item.nome or "").strip()
    cnpj = validadores.normalizar_cnpj(item.cnpj)
    cnpj = cnpj if cnpj and validadores.validar_cnpj(cnpj) else None  # CNPJ inválido é descartado, nunca "consertado"
    dominio = normalizar_dominio(item.site)
    tem_local = bool(item.cidade and normalizar_uf(item.estado))
    if len(nome) < 3 or not (cnpj or dominio or tem_local):
        return {"resultado": RES_REJEITADA, "empresa_id": None, "criterio": "DADOS_INSUFICIENTES"}

    achado = indice.localizar(item, provider, cnpj)
    if achado:
        criterio, empresa_id = achado
        _completar_vazios(conexao, empresa_id, item)
        _registrar_origem(conexao, empresa_id, item, provider, consulta, RES_EXISTENTE)
        indice.adicionar(empresa_id, item, provider, indice.cnpj_de.get(empresa_id))
        if cnpj and indice.cnpj_de.get(empresa_id) == cnpj:
            _gravar_incentivo(conexao, empresa_id, item.incentivo)
        return {"resultado": RES_EXISTENTE, "empresa_id": empresa_id, "criterio": criterio}

    parecido = indice.parecido(item)
    estagio = ESTAGIO_CONFIRMADA if cnpj else ESTAGIO_CANDIDATA
    agora = _agora().isoformat()
    uf = normalizar_uf(item.estado)
    cursor = conexao.execute(
        """INSERT INTO empresas (cnpj, razao_social, nome_fantasia, cidade, estado, status, criado_em, atualizado_em,
                                 dominio, estagio_cadastro, possivel_duplicata_de, origem_descoberta)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cnpj, nome, item.nome_fantasia, item.cidade, uf, None, agora, agora, dominio, estagio, parecido, provider))
    empresa_id = cursor.lastrowid
    if cnpj:
        _gravar_incentivo(conexao, empresa_id, item.incentivo)
    resultado = RES_POSSIVEL_DUPLICATA if parecido else (RES_NOVA_CONFIRMADA if cnpj else RES_NOVA_CANDIDATA)
    _registrar_origem(conexao, empresa_id, item, provider, consulta, resultado)
    indice.adicionar(empresa_id, item, provider, cnpj)
    return {"resultado": resultado, "empresa_id": empresa_id, "criterio": "PARECIDO" if parecido else None}


def promover_candidata(conexao: sqlite3.Connection, empresa_id: int, cnpj: str | None = None, justificativa: str = "") -> dict:
    """A EQUIPE valida uma candidata. Com CNPJ informado (validado pelos dígitos verificadores) ela vira CONFIRMADA e entra na base
    de prospects; sem CNPJ só é promovida com justificativa registrada (segue sem CNPJ e fora da fila de enriquecimento)."""
    linha = conexao.execute("SELECT estagio_cadastro, cnpj FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    if linha is None:
        return {"ok": False, "motivo": "Empresa não encontrada."}
    if linha[0] != ESTAGIO_CANDIDATA:
        return {"ok": False, "motivo": "A empresa já está confirmada."}
    novo = None
    if cnpj:
        novo = validadores.normalizar_cnpj(cnpj)
        if not novo or not validadores.validar_cnpj(novo):
            return {"ok": False, "motivo": "CNPJ inválido (dígitos verificadores não conferem)."}
        if conexao.execute("SELECT 1 FROM empresas WHERE cnpj = ? AND id != ?", (novo, empresa_id)).fetchone():
            return {"ok": False, "motivo": "Este CNPJ já pertence a outra empresa cadastrada — verifique se é duplicata."}
    elif not justificativa.strip():
        return {"ok": False, "motivo": "Sem CNPJ, informe a justificativa da validação manual."}
    conexao.execute("UPDATE empresas SET cnpj = COALESCE(?, cnpj), estagio_cadastro = ?, atualizado_em = ? WHERE id = ?",
                    (novo, ESTAGIO_CONFIRMADA, _agora().isoformat(), empresa_id))
    conexao.commit()
    return {"ok": True, "motivo": ""}


# ------------------------------------------------------------------ consultas por nível
def _ufs_do_perfil(perfil: dict) -> list[str]:
    ufs = [normalizar_uf(e) for e in perfil.get("estados", [])]
    return [u for u in dict.fromkeys(ufs) if u] or ["SP"]


def montar_consultas(perfil: dict, nivel: int, limite: int = 25, setor: str | None = None) -> list[Consulta]:
    ufs = _ufs_do_perfil(perfil)
    if nivel == 1:
        return [Consulta(1, ufs[0], cidade, setor, limite=limite) for cidade in perfil.get("cidades", [])]
    if nivel == 2:
        return [Consulta(2, uf, None, setor, limite=limite) for uf in ufs]
    if nivel == 3:
        return [Consulta(3, uf, None, setor, limite=limite) for uf in UFS_EXPANSAO if uf not in ufs]
    return [Consulta(4, None, None, setor, limite=limite)]


def _carregar_cursor(conexao, chave: str, inicial: tuple[dict, bool] | None = None) -> tuple[dict, bool]:
    linha = conexao.execute("SELECT cursor_json, concluido FROM descoberta_estado WHERE chave = ?", (chave,)).fetchone()
    if linha:
        return json.loads(linha[0]), bool(linha[1])
    cursor, concluido = inicial or ({}, False)
    return dict(cursor), bool(concluido)


def _salvar_cursor(conexao, chave: str, cursor: dict, concluido: bool) -> None:
    conexao.execute(
        """INSERT INTO descoberta_estado (chave, cursor_json, concluido, atualizado_em) VALUES (?, ?, ?, ?)
           ON CONFLICT (chave) DO UPDATE SET cursor_json = excluded.cursor_json, concluido = excluded.concluido,
                                             atualizado_em = excluded.atualizado_em""",
        (chave, json.dumps(cursor), int(concluido), _agora().isoformat()))
    conexao.commit()


def _estado_inicial_salic(uf: str | None) -> tuple[dict, bool]:
    """Herda de onde a coleta diária antiga parou (offset e 'UF concluída'), para não reler páginas já ingeridas."""
    try:
        from coleta import coleta_diaria

        estado = coleta_diaria._carregar_estado().get(uf or "", {})
        return ({"offset": int(estado.get("offset", 0))}, bool(estado.get("concluido"))) if estado else ({}, False)
    except Exception:
        return {}, False


# ------------------------------------------------------------------ orquestração
def _contadores_vazios() -> dict:
    return {"chamadas": 0, "creditos": 0.0, "encontradas": 0, "novas_confirmadas": 0, "novas_candidatas": 0, "existentes": 0,
            "possiveis_duplicatas": 0, "rejeitadas": 0}


def executar_descoberta(conexao: sqlite3.Connection, providers: list[CompanyDiscoveryProvider], perfil: dict, meta: int | None = None,
                        origem: str = "MANUAL", niveis: tuple[int, ...] = (1, 2, 3, 4), setor: str | None = None,
                        reconciliar: bool = True) -> dict:
    """Roda a descoberta até `meta` empresas NOVAS (padrão: EMPRESAS_NOVAS_POR_DIA), do nível 1 ao 4. Nenhum provedor derruba os outros."""
    criar_tabelas(conexao)
    meta = empresas_novas_por_dia() if meta is None else meta
    inicio = _agora()
    execucao_id = conexao.execute("INSERT INTO descoberta_execucoes (iniciado_em, origem, meta, status) VALUES (?, ?, ?, 'EXECUTANDO')",
                                  (inicio.isoformat(), origem, meta)).lastrowid
    conexao.commit()
    indice = IndiceDedupe(conexao)
    por_provider = {p.nome: {"status": None, "detalhe": "", **_contadores_vazios()} for p in providers}
    novas_total = 0
    parar: dict[str, bool] = {}

    for p in providers:  # situação inicial (desligado / sem credencial / sem cota)
        info = por_provider[p.nome]
        if not provider_habilitado(conexao, p):
            info["status"], info["detalhe"], parar[p.nome] = STATUS_DESABILITADO, "Desligado nas configurações.", True
            continue
        st = p.status(conexao)
        if st["estado"] != STATUS_DISPONIVEL:
            info["status"], info["detalhe"], parar[p.nome] = st["estado"], st["motivo"], True

    for nivel in niveis:
        if novas_total >= meta:
            break
        for p in providers:
            if parar.get(p.nome) or nivel not in p.niveis_suportados:
                continue
            info = por_provider[p.nome]
            limite_prov = limite_por_provider(p.nome)
            for base in montar_consultas(perfil, nivel, limite=min(100, max(limite_prov, 10)), setor=setor):
                if novas_total >= meta or parar.get(p.nome):
                    break
                chave = base.chave(p.nome)
                cursor, concluido = _carregar_cursor(conexao, chave, _estado_inicial_salic(base.uf) if p.nome == "SALIC" else None)
                if concluido:
                    continue
                while (novas_total < meta and info["chamadas"] < max_chamadas_por_provider()
                       and (info["novas_confirmadas"] + info["novas_candidatas"] + info["possiveis_duplicatas"]) < limite_prov):
                    orc = p.orcamento(conexao)
                    if orc is not None and orc <= 0:
                        info["status"], info["detalhe"], parar[p.nome] = STATUS_SEM_COTA, "Teto de uso do mês atingido.", True
                        break
                    consulta = Consulta(base.nivel, base.uf, base.cidade, base.setor, base.tema, base.porte, base.limite, cursor)
                    try:
                        resultado = p.buscar(consulta)
                    except ProvedorSemCredencial as erro:
                        info["status"], info["detalhe"], parar[p.nome] = STATUS_SEM_CREDENCIAL, str(erro), True
                        registrar_evento(conexao, p.nome, f"busca nível {nivel}", sucesso=False, detalhe=str(erro))
                        break
                    except ProvedorSemCota as erro:
                        info["status"], info["detalhe"], parar[p.nome] = STATUS_SEM_COTA, str(erro), True
                        registrar_evento(conexao, p.nome, f"busca nível {nivel}", sucesso=False, detalhe=str(erro))
                        break
                    except ProvedorIndisponivel as erro:
                        info["status"], info["detalhe"], parar[p.nome] = STATUS_INDISPONIVEL, str(erro), True
                        registrar_evento(conexao, p.nome, f"busca nível {nivel}", sucesso=False, detalhe=str(erro))
                        break
                    except Exception as erro:  # nenhum provedor com bug derruba a rotina
                        info["status"], info["detalhe"], parar[p.nome] = STATUS_ERRO, f"{type(erro).__name__}: {erro}", True
                        registrar_evento(conexao, p.nome, f"busca nível {nivel}", sucesso=False, detalhe=info["detalhe"])
                        break
                    info["chamadas"] += resultado.chamadas
                    info["creditos"] += resultado.creditos
                    info["encontradas"] += len(resultado.empresas)
                    registrar_evento(conexao, p.nome, f"busca nível {nivel}" + (f" {base.uf}" if base.uf else "")
                                     + (f" {base.cidade}" if base.cidade else ""), len(resultado.empresas), resultado.creditos, True)
                    if resultado.creditos:
                        fila_enriquecimento.registrar_uso(conexao, p.nome, int(max(1, round(resultado.creditos))))
                    truncado = False
                    for item in resultado.empresas:
                        if novas_total >= meta or (info["novas_confirmadas"] + info["novas_candidatas"] + info["possiveis_duplicatas"]) >= limite_prov:
                            truncado = True  # sobrou item da página: o cursor NÃO avança (a releitura só encontra "existentes")
                            break
                        r = ingerir(conexao, item, p.nome, indice, consulta)
                        chave_r = {RES_NOVA_CONFIRMADA: "novas_confirmadas", RES_NOVA_CANDIDATA: "novas_candidatas", RES_EXISTENTE: "existentes",
                                   RES_POSSIVEL_DUPLICATA: "possiveis_duplicatas", RES_REJEITADA: "rejeitadas"}[r["resultado"]]
                        info[chave_r] += 1
                        if r["resultado"] in (RES_NOVA_CONFIRMADA, RES_NOVA_CANDIDATA, RES_POSSIVEL_DUPLICATA):
                            novas_total += 1
                    conexao.commit()
                    if truncado:
                        break
                    cursor = resultado.proximo_cursor or cursor
                    _salvar_cursor(conexao, chave, cursor, resultado.esgotado)
                    if resultado.esgotado:
                        break

    for p in providers:  # quem rodou sem problema fecha como CONCLUIDO
        info = por_provider[p.nome]
        if info["status"] is None:
            info["status"] = STATUS_CONCLUIDO if info["chamadas"] else STATUS_DISPONIVEL
            if not info["chamadas"]:
                info["detalhe"] = "Nada a fazer nesta execução (níveis/limites ou cursor concluído)."

    if reconciliar:
        from processamento import relacionamento

        relacionamento.reconciliar_relacionamentos(conexao)  # evidência real de incentivo pode tornar uma empresa Linha Cruzada
        conexao.commit()

    totais = {k: sum(i[k] for i in por_provider.values()) for k in _contadores_vazios()}
    totais["novas_total"] = novas_total
    status = _status_geral(por_provider, novas_total, meta)
    resumo = {"execucao_id": execucao_id, "status": status, "meta": meta, "providers": por_provider, "totais": totais,
              "iniciado_em": inicio.isoformat(), "finalizado_em": _agora().isoformat()}
    conexao.execute("UPDATE descoberta_execucoes SET finalizado_em = ?, status = ?, resumo_json = ? WHERE id = ?",
                    (resumo["finalizado_em"], status, json.dumps(resumo, ensure_ascii=False), execucao_id))
    for nome, i in por_provider.items():
        conexao.execute(
            """INSERT INTO descoberta_itens (execucao_id, provider, status, chamadas, creditos, encontradas, novas_confirmadas, novas_candidatas,
                   existentes, possiveis_duplicatas, rejeitadas, detalhe) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (execucao_id, nome, i["status"], i["chamadas"], i["creditos"], i["encontradas"], i["novas_confirmadas"], i["novas_candidatas"],
             i["existentes"], i["possiveis_duplicatas"], i["rejeitadas"], i["detalhe"]))
    conexao.commit()
    return resumo


def _status_geral(por_provider: dict, novas: int, meta: int) -> str:
    """CONCLUIDO | PARCIAL | SEM_COTA | FALHOU (vocabulário da Rotina diária, sem 'Pendente'/'Executando' que são transitórios)."""
    if meta <= 0 or novas >= meta:
        return "CONCLUIDO"
    rodaram = [i for i in por_provider.values() if i["status"] not in (STATUS_DESABILITADO, STATUS_SEM_CREDENCIAL)]
    if not rodaram:
        return "FALHOU"  # nenhum provedor ligado e com credencial
    problemas = [i["status"] for i in rodaram if i["status"] in (STATUS_INDISPONIVEL, STATUS_ERRO, STATUS_SEM_COTA)]
    if novas == 0 and len(problemas) == len(rodaram):
        return "SEM_COTA" if all(s == STATUS_SEM_COTA for s in problemas) else "FALHOU"
    return "PARCIAL"  # a meta não foi atingida: fontes esgotadas, provedor sem cota/credencial ou falha parcial


# ------------------------------------------------------------------ leitura para a interface
def situacao_providers(conexao: sqlite3.Connection, providers: list[CompanyDiscoveryProvider] | None = None) -> list[dict]:
    """Uma linha por provedor: estado, habilitado, última execução, descobertas e uso — tudo vindo do banco."""
    criar_tabelas(conexao)
    linhas = []
    for p in providers or providers_padrao():
        st = p.status(conexao)
        ultimo = conexao.execute(
            """SELECT e.iniciado_em, i.status, i.encontradas, i.novas_confirmadas + i.novas_candidatas AS novas, i.existentes,
                      i.possiveis_duplicatas, i.detalhe
               FROM descoberta_itens i JOIN descoberta_execucoes e ON e.id = i.execucao_id WHERE i.provider = ? ORDER BY e.id DESC LIMIT 1""",
            (p.nome,)).fetchone()
        totais = conexao.execute(
            "SELECT COUNT(*), SUM(resultado = ?), SUM(resultado = ?) FROM empresas_origens WHERE provider = ?",
            (RES_EXISTENTE, RES_POSSIVEL_DUPLICATA, p.nome)).fetchone()
        erros = conexao.execute("SELECT COUNT(*) FROM uso_api_eventos WHERE provider = ? AND sucesso = 0", (p.nome,)).fetchone()[0]
        orc = p.orcamento(conexao)
        linhas.append({
            "provider": p.nome, "rotulo": p.rotulo, "capacidade": p.capacidade, "custo": p.custo, "acesso": p.acesso,
            "estado": st["estado"], "motivo": st["motivo"], "habilitado": provider_habilitado(conexao, p),
            "niveis": p.niveis_suportados, "validado": p.validado_em_producao, "observacao_validacao": p.observacao_validacao,
            "ultima_execucao": ultimo[0] if ultimo else None, "ultimo_status": ultimo[1] if ultimo else None,
            "ultimo_detalhe": ultimo[6] if ultimo else None,
            "origens_registradas": totais[0] or 0, "existentes": totais[1] or 0, "possiveis_duplicatas": totais[2] or 0, "erros": erros,
            "creditos_no_mes": creditos_do_mes(conexao, p.nome), "orcamento_restante": orc,
            "limite_por_execucao": limite_por_provider(p.nome),
        })
    return linhas


def contar_candidatas(conexao: sqlite3.Connection) -> int:
    if not _tabela_existe(conexao, "empresas") or "estagio_cadastro" not in {l[1] for l in conexao.execute("PRAGMA table_info(empresas)")}:
        return 0
    return conexao.execute("SELECT COUNT(*) FROM empresas WHERE estagio_cadastro = ?", (ESTAGIO_CANDIDATA,)).fetchone()[0]
