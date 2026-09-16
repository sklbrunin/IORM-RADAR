"""Camada de abstração para busca de presença digital/contatos na
internet (módulo de Inteligência de Contatos). Permite trocar de
provedor de busca no futuro sem reescrever o resto do sistema — é só
implementar uma nova classe `SearchProvider` e registrar em
`obter_provider_ativo()`.

Pesquisa feita ANTES de escolher um provedor (ver docs/decisoes.md para
a comparação completa):
  - Google Custom Search JSON API: fechada para novos clientes desde
    2026, será descontinuada em 2027 — não é uma opção viável para um
    projeto novo.
  - Bing Web Search API: aposentada pela Microsoft em agosto de 2025.
  - Brave Search API: removeu o tier gratuito em fevereiro de 2026;
    hoje exige cartão de crédito (créditos mensais de US$5, ~1.000
    buscas/mês).
  - SerpApi: tem tier gratuito real (100-250 buscas/mês, sem cartão
    para começar), é bem documentada, e cobre Google com geolocalização
    (Brasil). Escolhida como primeira implementação de referência.

IMPORTANTE — honestidade sobre teste: esta implementação NÃO foi
testada contra a API real do SerpApi neste ambiente, porque não existe
uma chave configurada aqui. A lógica de montagem da requisição e de
leitura da resposta foi validada em testes automatizados usando uma
resposta de exemplo fiel ao formato documentado publicamente pelo
SerpApi (ver testes/test_busca_providers.py) — isso confirma que o
CÓDIGO está correto, mas não substitui um teste ao vivo com chave real."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests


@dataclass
class ResultadoBusca:
    titulo: str
    url: str
    trecho: str | None = None


class SearchProvider(ABC):
    nome: str = "desconhecido"

    #: Mensagem amigável (pt-BR) sobre a última falha de `buscar()`, se
    #: houver. `None` quando a última busca teve sucesso (mesmo que com
    #: zero resultados — "não achei nada" é diferente de "a busca falhou").
    ultimo_erro: str | None = None

    @abstractmethod
    def disponivel(self) -> bool:
        """True se este provider está configurado e pronto pra uso real
        (ex: chave de API presente no ambiente)."""

    @abstractmethod
    def buscar(self, query: str, num_resultados: int = 5) -> list[ResultadoBusca]:
        """Executa uma busca e devolve resultados reais. Nunca inventa
        resultado — se a API falhar, não retornar nada ou o provider não
        estiver disponível, devolve lista vazia e registra o motivo em
        `ultimo_erro` para a UI poder mostrar uma mensagem amigável."""


class SerpApiProvider(SearchProvider):
    """Implementação real usando a Search API do SerpApi
    (https://serpapi.com/search-api), motor "google" com geolocalização
    Brasil. Requer SERPAPI_API_KEY no ambiente (ver .env.example)."""

    nome = "SerpApi"
    _URL = "https://serpapi.com/search"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key if api_key is not None else os.environ.get("SERPAPI_API_KEY")

    def disponivel(self) -> bool:
        return bool(self._api_key)

    def buscar(self, query: str, num_resultados: int = 5) -> list[ResultadoBusca]:
        self.ultimo_erro = None
        if not self.disponivel():
            self.ultimo_erro = "Nenhuma chave SERPAPI_API_KEY configurada."
            return []
        parametros = {
            "q": query,
            "api_key": self._api_key,
            "engine": "google",
            "gl": "br",
            "hl": "pt-br",
            "num": num_resultados,
        }
        try:
            resposta = requests.get(self._URL, params=parametros, timeout=20)
        except requests.Timeout:
            self.ultimo_erro = "A SerpApi demorou demais para responder (timeout). Tente novamente em alguns minutos."
            return []
        except requests.RequestException:
            self.ultimo_erro = "Não foi possível conectar à SerpApi — verifique a conexão com a internet."
            return []

        if resposta.status_code == 401:
            self.ultimo_erro = "A chave da SerpApi foi rejeitada (inválida, expirada ou revogada). Confira SERPAPI_API_KEY no .env."
            return []
        if resposta.status_code == 429:
            self.ultimo_erro = "O limite de buscas do plano da SerpApi foi atingido neste período. Tente novamente mais tarde ou aguarde a renovação do plano."
            return []
        try:
            resposta.raise_for_status()
            dados = resposta.json()
        except (requests.HTTPError, ValueError):
            self.ultimo_erro = f"A SerpApi respondeu com um erro inesperado (HTTP {resposta.status_code})."
            return []

        if dados.get("error"):
            # A SerpApi às vezes devolve HTTP 200 com um campo "error" no corpo
            # (ex: chave inválida, parâmetro rejeitado) — sem isso, um erro real
            # apareceria pro usuário como "nenhum resultado encontrado".
            self.ultimo_erro = f"A SerpApi retornou um erro: {dados['error']}"
            return []

        return self._parse_resposta(dados, num_resultados)

    @staticmethod
    def _parse_resposta(dados: dict, num_resultados: int) -> list[ResultadoBusca]:
        """Separado de buscar() de propósito: permite testar a leitura
        da resposta sem precisar fazer uma chamada de rede de verdade."""
        organicos = dados.get("organic_results") or []
        resultados: list[ResultadoBusca] = []
        for item in organicos[:num_resultados]:
            titulo = item.get("title")
            url = item.get("link")
            if not titulo or not url:
                continue
            resultados.append(ResultadoBusca(titulo=titulo, url=url, trecho=item.get("snippet")))
        return resultados


class FilaManualProvider(SearchProvider):
    """Provider "nulo": representa o comportamento que o sistema já
    tinha antes desta arquitetura existir — sem API de busca
    configurada, a pesquisa vira uma entrada na fila manual, processada
    por um agente com ferramentas de busca fora do navegador. Sempre
    "disponível" porque é o fallback garantido."""

    nome = "Fila manual (nenhuma API de busca configurada)"

    def disponivel(self) -> bool:
        return True

    def buscar(self, query: str, num_resultados: int = 5) -> list[ResultadoBusca]:
        return []


def obter_provider_ativo() -> SearchProvider:
    """Escolhe qual provider usar: SerpApi se houver chave configurada
    em SERPAPI_API_KEY, senão o fallback de fila manual. Este é o único
    lugar do sistema que decide isso — plugar um novo provedor no
    futuro (Brave, Tavily etc.) é só adicionar outra classe e um `if`
    aqui, sem tocar em mais nada."""
    serpapi = SerpApiProvider()
    if serpapi.disponivel():
        return serpapi
    return FilaManualProvider()
