"""Camada de provedores de contato — para trocar de fornecedor sem reescrever o sistema.

Fluxo:  PROVEDOR -> BUSCA -> NORMALIZAÇÃO -> VALIDAÇÃO -> BANCO -> EVIDÊNCIA/FONTE -> CRM
  * Provedor  : subclasse de ContactProvider (abaixo). Só sabe buscar e devolver
                `ContatoEncontrado`/`PresencaEncontrada` já com fonte e URL.
  * Normalização/validação/banco/evidência: `persistir()` — única porta de entrada
                para gravar; reaproveita processamento/enriquecimento.py (e-mail,
                telefone, URL, níveis de confiança) e processamento/banco.py.
  * CRM       : os contatos gravados aparecem na ficha e no módulo Contatos, de
                onde "Adicionar ao CRM" já parte (contato_id em crm_oportunidades).

Provedores incluídos (ver docs/decisoes.md item 8.x para a avaliação completa):
  ReceitaFederalContactProvider  BrasilAPI (dados públicos do CNPJ: situação, CNAE,
                                 telefone cadastral, sócios/administradores). GRATUITO,
                                 sem chave. Testado ao vivo.
  WebSearchContactProvider       Busca web via SerpApi (site, redes, e-mail/telefone
                                 citados, pessoa+cargo em resultado público).
                                 CAMADA GRATUITA LIMITADA — precisa SERPAPI_API_KEY.
  HunterContactProvider          Hunter.io Domain Search (e-mail profissional por pessoa).
                                 PAGO (API exige plano pago) — precisa HUNTER_API_KEY.
                                 Preparado e testado só com resposta simulada no formato
                                 documentado; NUNCA rodou contra a API real.

Regras de ouro que a camada garante, seja qual for o provedor:
  * e-mail genérico (financeiro@, contato@) é gravado como INSTITUCIONAL, com a
    ÁREA da caixa postal — jamais como "e-mail de fulano";
  * pessoa só existe com nome + cargo vindos da fonte;
  * tudo grava fonte, URL e data; nenhum resultado automático nasce com confiança ALTO
    (exceto fatos de registro oficial, ex: sócio no QSA da Receita Federal)."""
from __future__ import annotations

import os
import re
import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import requests

from processamento import banco, busca_providers, enriquecimento, pesquisa_empresa

CUSTO_GRATUITO = "GRATUITO"
CUSTO_CAMADA_GRATUITA = "CAMADA_GRATUITA"
CUSTO_PAGO = "PAGO"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ContatoEncontrado:
    tipo_contato: str  # EMAIL_INSTITUCIONAL, EMAIL_CONTATO, TELEFONE_INSTITUCIONAL, PESSOA_CARGO, ...
    valor: str  # e-mail, telefone ou (PESSOA_CARGO) URL/referência pública
    fonte: str
    url_fonte: str | None
    nivel_confianca: str = "BAIXO"
    nome: str | None = None
    cargo: str | None = None
    departamento: str | None = None
    email_profissional: str | None = None  # só quando a fonte liga o e-mail à PESSOA


@dataclass
class ResultadoProvider:
    provider: str
    contatos: list[ContatoEncontrado] = field(default_factory=list)
    atualizacoes_empresa: dict = field(default_factory=dict)  # ex: {"status": "ATIVA", "nome_fantasia": "..."}
    evidencias: list[dict] = field(default_factory=list)
    chamadas_api: int = 0
    erros: list[str] = field(default_factory=list)
    persistido_diretamente: bool = False  # provedores legados que já gravam sozinhos
    contagens_diretas: dict = field(default_factory=dict)
    ignorado_motivo: str | None = None  # ex: "sem CNPJ", "limite mensal atingido"


class ContactProvider(ABC):
    nome: str = "desconhecido"
    custo: str = CUSTO_GRATUITO
    credencial_env: str | None = None  # nome da variável de ambiente exigida (nunca o valor)

    def disponivel(self) -> bool:
        return self.credencial_env is None or bool(os.environ.get(self.credencial_env))

    @abstractmethod
    def enriquecer(self, empresa: dict, **opcoes) -> ResultadoProvider:
        """`empresa`: dict com id, razao_social, cnpj, cidade, estado (+ site, se conhecido).
        Nunca lança exceção: falhas vão em `erros`."""


# ------------------------------------------------------------------ Receita Federal (BrasilAPI)
class ReceitaFederalContactProvider(ContactProvider):
    nome = "BrasilAPI / Receita Federal"
    custo = CUSTO_GRATUITO
    URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"

    def __init__(self, buscador: Callable[[str], tuple[int, dict | None]] | None = None, pausa: float = 0.5):
        self._buscador = buscador or self._buscar_http
        self._pausa = pausa

    @staticmethod
    def _buscar_http(url: str) -> tuple[int, dict | None]:
        resposta = requests.get(url, timeout=25, headers={"User-Agent": "IORMRadar/1.0", "Accept": "application/json"})
        try:
            return resposta.status_code, resposta.json() if resposta.text.strip().startswith("{") else None
        except ValueError:
            return resposta.status_code, None

    def enriquecer(self, empresa: dict, **opcoes) -> ResultadoProvider:
        resultado = ResultadoProvider(provider=self.nome)
        cnpj = re.sub(r"\D", "", empresa.get("cnpj") or "")
        if len(cnpj) != 14:
            resultado.ignorado_motivo = "empresa sem CNPJ confirmado"
            return resultado
        url = self.URL.format(cnpj=cnpj)
        try:
            status, dados = self._buscador(url)
        except Exception as exc:
            resultado.erros.append(f"{self.nome}: falha de rede ({type(exc).__name__})")
            return resultado
        resultado.chamadas_api = 1
        if self._pausa:
            time.sleep(self._pausa)
        if status == 404:
            resultado.erros.append(f"{self.nome}: CNPJ não encontrado na base pública")
            return resultado
        if status == 429:
            resultado.erros.append(f"{self.nome}: limite de requisições atingido, tentar mais tarde")
            return resultado
        if status != 200 or not dados:
            resultado.erros.append(f"{self.nome}: resposta inesperada (HTTP {status})")
            return resultado

        fonte = f"BrasilAPI / Receita Federal (dados públicos do CNPJ {cnpj})"
        situacao = (dados.get("descricao_situacao_cadastral") or "").strip()
        if situacao:
            resultado.atualizacoes_empresa["status"] = situacao.title()
        if (dados.get("nome_fantasia") or "").strip():
            resultado.atualizacoes_empresa["nome_fantasia"] = dados["nome_fantasia"].strip().title()
        if dados.get("cnae_fiscal_descricao"):
            resultado.evidencias.append({
                "categoria": "OUTRO",
                "descricao": f"CNAE principal {dados.get('cnae_fiscal')}: {dados['cnae_fiscal_descricao']} "
                             f"(situação cadastral: {situacao or 'não informada'}).",
                "url": url, "fonte": fonte, "nivel_confianca": "ALTO",
            })

        for campo in ("ddd_telefone_1", "ddd_telefone_2"):
            telefone = enriquecimento.normalizar_telefone(dados.get(campo))
            if telefone:
                resultado.contatos.append(ContatoEncontrado(
                    tipo_contato="TELEFONE_INSTITUCIONAL", valor=telefone, fonte=fonte, url_fonte=url, nivel_confianca="MEDIO",
                ))
        email = enriquecimento.normalizar_email(dados.get("email"))
        if email:
            resultado.contatos.append(ContatoEncontrado(
                tipo_contato="EMAIL_INSTITUCIONAL", valor=email, fonte=fonte, url_fonte=url, nivel_confianca="MEDIO",
                departamento=enriquecimento.area_do_email(email),
            ))
        for socio in dados.get("qsa") or []:
            nome = enriquecimento.normalizar_nome_pessoa(socio.get("nome_socio"))
            qualificacao = (socio.get("qualificacao_socio") or "").strip()
            if not nome or not qualificacao:
                continue  # sem nome e qualificação registrados, não vira "responsável"
            # Só nome + qualificação: CPF (mascarado), faixa etária etc. NÃO são guardados (LGPD).
            resultado.contatos.append(ContatoEncontrado(
                tipo_contato="PESSOA_CARGO", valor=f"referencia-publica:{nome.lower()}", nome=nome,
                cargo=f"{qualificacao} (quadro societário — Receita Federal)",
                departamento=None, fonte=fonte, url_fonte=url, nivel_confianca="ALTO",
            ))
        return resultado


# ------------------------------------------------------------------ Busca web (SerpApi)
class WebSearchContactProvider(ContactProvider):
    nome = "Busca web (SerpApi)"
    custo = CUSTO_CAMADA_GRATUITA
    credencial_env = "SERPAPI_API_KEY"

    def __init__(self, conexao: sqlite3.Connection, provider: busca_providers.SearchProvider | None = None):
        self._conexao = conexao
        self._provider = provider

    def enriquecer(self, empresa: dict, consultas: list | None = None, **opcoes) -> ResultadoProvider:
        resultado = ResultadoProvider(provider=self.nome, persistido_diretamente=True)
        provider = self._provider or busca_providers.obter_provider_ativo()
        if isinstance(provider, busca_providers.FilaManualProvider):
            resultado.ignorado_motivo = "SERPAPI_API_KEY não configurada"
            return resultado
        resumo = pesquisa_empresa.pesquisar_empresa(
            self._conexao, empresa["id"], empresa["razao_social"], empresa.get("cidade"), empresa.get("estado"),
            provider=provider, consultas=consultas, registrar_historico=False,
        )
        resultado.chamadas_api = resumo.get("consultas_executadas", 0)
        resultado.erros.extend(resumo.get("erros", []))
        resultado.contagens_diretas = {
            "presenca_digital": resumo["presenca_digital"], "evidencias": resumo["evidencias"], "contatos": resumo["contatos"],
        }
        return resultado


# ------------------------------------------------------------------ Hunter.io (pago) — preparado
class HunterContactProvider(ContactProvider):
    """Hunter Domain Search. Cobre e-mail PROFISSIONAL por pessoa (com cargo e
    departamento), mas a API exige plano pago e a cobertura de PMEs brasileiras
    é incerta. Requer `HUNTER_API_KEY` no .env e o domínio da empresa (site já
    encontrado). Resposta interpretada conforme a documentação pública; nunca
    testado contra a API real (sem credencial)."""

    nome = "Hunter.io"
    custo = CUSTO_PAGO
    credencial_env = "HUNTER_API_KEY"
    URL = "https://api.hunter.io/v2/domain-search"

    def __init__(self, buscador: Callable[[str, dict], dict] | None = None):
        self._buscador = buscador or (lambda url, params: requests.get(url, params=params, timeout=25).json())

    @staticmethod
    def _dominio(site: str | None) -> str | None:
        if not site:
            return None
        m = re.match(r"https?://(?:www\.)?([^/:]+)", site.strip().lower())
        return m.group(1) if m else None

    def enriquecer(self, empresa: dict, **opcoes) -> ResultadoProvider:
        resultado = ResultadoProvider(provider=self.nome)
        dominio = self._dominio(empresa.get("site"))
        if not dominio:
            resultado.ignorado_motivo = "domínio da empresa (site) ainda não conhecido"
            return resultado
        chave = os.environ.get(self.credencial_env or "")
        if not chave:
            resultado.ignorado_motivo = f"{self.credencial_env} não configurada"
            return resultado
        try:
            corpo = self._buscador(self.URL, {"domain": dominio, "api_key": chave, "limit": 10})
        except Exception as exc:
            resultado.erros.append(f"{self.nome}: falha de rede ({type(exc).__name__})")
            return resultado
        resultado.chamadas_api = 1
        if corpo.get("errors"):
            resultado.erros.append(f"{self.nome}: {corpo['errors'][0].get('details', 'erro da API')}")
            return resultado
        for item in (corpo.get("data") or {}).get("emails", []):
            email = enriquecimento.normalizar_email(item.get("value"))
            if not email:
                continue
            fontes = item.get("sources") or []
            url_fonte = fontes[0].get("uri") if fontes else None
            nome = " ".join(p for p in [item.get("first_name"), item.get("last_name")] if p) or None
            confianca = "MEDIO" if (item.get("confidence") or 0) >= 80 else "BAIXO"
            if item.get("type") == "personal" and nome and item.get("position"):
                resultado.contatos.append(ContatoEncontrado(
                    tipo_contato="PESSOA_CARGO", valor=email, nome=nome, cargo=item["position"],
                    departamento=(enriquecimento.classificar_area(item["position"])
                                  or enriquecimento.classificar_area(item.get("department"))),
                    email_profissional=email, fonte=f"{self.nome} (Domain Search)", url_fonte=url_fonte,
                    nivel_confianca=confianca,
                ))
            else:  # genérico, ou pessoal sem cargo: fica INSTITUCIONAL, nunca vira "responsável"
                resultado.contatos.append(ContatoEncontrado(
                    tipo_contato="EMAIL_CONTATO", valor=email, departamento=enriquecimento.area_do_email(email),
                    fonte=f"{self.nome} (Domain Search)", url_fonte=url_fonte, nivel_confianca="BAIXO",
                ))
        return resultado


# ------------------------------------------------------------------ persistência (normalização + validação + banco + evidência)
def persistir(conexao: sqlite3.Connection, empresa_id: int, resultado: ResultadoProvider) -> dict:
    """Única porta de gravação dos provedores. Valida de novo o que vem de fora
    (e-mail, telefone), nunca rebaixa/atualiza cadastro que já tem valor e nunca
    grava nível ALTO fora de registro oficial."""
    agora = _agora()
    contagem = {"contatos": 0, "evidencias": 0, "cadastro": 0}

    for contato in resultado.contatos:
        valor = contato.valor
        if contato.tipo_contato.startswith("EMAIL"):
            valor = enriquecimento.normalizar_email(valor)
        elif contato.tipo_contato.startswith("TELEFONE"):
            valor = enriquecimento.normalizar_telefone(valor)
        if not valor:
            continue
        if contato.tipo_contato == "PESSOA_CARGO" and not (contato.nome and contato.cargo):
            continue  # pessoa sem nome+cargo na fonte não é gravada
        nivel = contato.nivel_confianca
        if nivel == "ALTO" and "Receita Federal" not in contato.fonte:
            nivel = "MEDIO"
        _, criado = banco.inserir_ou_atualizar_contato(conexao, {
            "empresa_id": empresa_id, "nome": contato.nome, "cargo": contato.cargo,
            "departamento": contato.departamento or enriquecimento.classificar_area(contato.cargo),
            "tipo_contato": contato.tipo_contato, "valor": valor,
            "prioridade": enriquecimento.classificar_prioridade(contato.cargo or contato.departamento),
            "fonte": contato.fonte, "url_fonte": contato.url_fonte, "coletado_em": agora, "nivel_confianca": nivel,
        })
        contagem["contatos"] += 1 if criado else 0

    for ev in resultado.evidencias:
        try:
            categoria = enriquecimento.validar_categoria_evidencia(ev.get("categoria", "OUTRO"))
        except ValueError:
            categoria = "OUTRO"
        _, criada = banco.inserir_ou_atualizar_evidencia(conexao, {
            "empresa_id": empresa_id, "categoria": categoria, "descricao": ev["descricao"][:400], "url": ev.get("url"),
            "fonte": ev["fonte"], "coletado_em": agora, "nivel_confianca": ev.get("nivel_confianca", "BAIXO"),
        })
        contagem["evidencias"] += 1 if criada else 0

    for campo, valor in resultado.atualizacoes_empresa.items():
        if campo not in ("status", "nome_fantasia") or not valor:
            continue
        cursor = conexao.execute(
            f"UPDATE empresas SET {campo} = ?, atualizado_em = ? WHERE id = ? AND ({campo} IS NULL OR {campo} = '')",
            (valor, agora, empresa_id),
        )
        contagem["cadastro"] += cursor.rowcount
    conexao.commit()
    return contagem
