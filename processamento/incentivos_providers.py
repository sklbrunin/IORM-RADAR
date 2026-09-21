"""Camada de provedores de INCENTIVO: cada mecanismo (Lei Rouanet, esporte, ProAC, PRONON...) é um
provedor que devolve registros já normalizados; o resto do sistema (banco, empresas, dashboard) só
conhece o formato normalizado.

    IncentivoProvider  →  coletar()  →  RegistroIncentivo (normalizado)  →  ingerir()  →  empresas + incentivos

Regras:
  • Só há provedor "integrado" quando existe fonte pública, estruturada e verificada. Verificamos
    cada fonte de verdade (ver `INVESTIGACAO`): onde não há dado utilizável, o provedor existe só
    para registrar o motivo e levanta IntegracaoIndisponivel — nunca devolve dado inventado.
  • Cada incentivo guarda mecanismo, fonte, ano, empresa, CNPJ, projeto, valor, UF, município e URL
    (evidência). Deduplicação pela URL da fonte (a mesma coleta rodada de novo não duplica).
"""
from __future__ import annotations

import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Iterator

from processamento import banco, transformacao

MECANISMO_ROUANET = "LEI_ROUANET"
MECANISMO_LPIE = "LPIE_SP"
MECANISMO_LIE = "LIE_FEDERAL"
MECANISMO_PROAC_ICMS = "PROAC_ICMS_SP"
MECANISMO_PRONON_PRONAS = "PRONON_PRONAS_PCD"
MECANISMO_FIA_IDOSO = "FIA_FUNDO_IDOSO"

ROTULOS_MECANISMO = {
    MECANISMO_ROUANET: "Lei Rouanet (federal)",
    MECANISMO_LPIE: "Lei Paulista de Incentivo ao Esporte (SP)",
    MECANISMO_LIE: "Lei de Incentivo ao Esporte (federal)",
    MECANISMO_PROAC_ICMS: "ProAC ICMS (SP)",
    MECANISMO_PRONON_PRONAS: "PRONON / PRONAS-PCD (federal)",
    MECANISMO_FIA_IDOSO: "Fundos da Infância/Idoso (FIA)",
}

STATUS_INTEGRADO = "INTEGRADO"
STATUS_INDISPONIVEL = "INDISPONIVEL"

# Resultado da investigação de fontes (rodada v7, 18/09/2026). Cada linha é um fato verificado
# naquele dia — não uma suposição. Se a fonte mudar, o provedor correspondente é o único lugar a alterar.
INVESTIGACAO = {
    MECANISMO_ROUANET: (
        "API pública do SALIC/MinC (api.salic.cultura.gov.br): /incentivadores e /incentivadores/{id}/doacoes "
        "devolvem empresa, CNPJ, UF, município, valor, projeto (PRONAC) e data. Testada ao vivo."
    ),
    MECANISMO_LPIE: (
        "Dados Abertos SP (dataset lei-paulista-de-incentivo-ao-esporte): um único PDF com projetos em execução. "
        "Lista projetos, não os incentivadores (empresas) — não alimenta a base de empresas."
    ),
    MECANISMO_LIE: (
        "Nenhuma API/CSV oficial acessível sem credencial: o catálogo dados.gov.br respondeu HTTP 401 (exige token) e "
        "o painel oficial de transparência é interativo. O painel com patrocinadores é de terceiro (Prosas), não oficial."
    ),
    MECANISMO_PROAC_ICMS: (
        "Portais de consulta de projetos (fomentocultsp / vitrine de projetos) sem arquivo baixável verificado; o dataset "
        "FOMENTOS no Dados Abertos SP não tem URL de arquivo. A lista de empresas habilitadas é divulgada mensalmente sem "
        "formato estruturado localizado."
    ),
    MECANISMO_PRONON_PRONAS: (
        "O Ministério da Saúde publica listas de PROJETOS aprovados (DOU/Transferegov), não uma base pública de doadores; "
        "a página de doações exige autenticação."
    ),
    MECANISMO_FIA_IDOSO: (
        "As doações são declaradas à Receita (DBF) por cada conselho/fundo; não há base pública nacional por empresa."
    ),
}


class IntegracaoIndisponivel(RuntimeError):
    """O mecanismo não tem fonte pública estruturada suficientemente confiável para coleta."""


@dataclass
class RegistroIncentivo:
    empresa: dict     # cnpj, razao_social, nome_fantasia, cidade, estado, status
    incentivo: dict   # mecanismo, fonte, tipo_incentivo, projeto, ano, valor, uf, cidade, url_fonte, coletado_em, nivel_confianca


class IncentivoProvider(ABC):
    codigo: str = ""
    nome: str = ""
    esfera: str = ""
    fonte_nome: str = ""
    fonte_url: str | None = None
    status: str = STATUS_INDISPONIVEL

    @property
    def investigacao(self) -> str:
        return INVESTIGACAO.get(self.codigo, "")

    @abstractmethod
    def coletar(self, uf: str, max_paginas: int | None = None, **opcoes) -> Iterator[RegistroIncentivo]:
        """Gera registros normalizados. Não grava nada."""


Paginador = Callable[[str, int], dict]  # (uf, offset) -> payload JSON da API


class SalicRouanetProvider(IncentivoProvider):
    codigo = MECANISMO_ROUANET
    nome = ROTULOS_MECANISMO[MECANISMO_ROUANET]
    esfera = "Federal"
    fonte_nome = "SALIC - Sistema de Apoio às Leis de Incentivo à Cultura (Lei Rouanet)"
    fonte_url = "https://api.salic.cultura.gov.br/api/v1/incentivadores"
    status = STATUS_INTEGRADO
    LIMITE_POR_PAGINA = 100

    def __init__(self, paginador: Paginador | None = None, pausa: float = 0.3):
        self._paginador = paginador or self._paginar_http
        self._pausa = pausa

    def _paginar_http(self, uf: str, offset: int) -> dict:
        import requests

        resposta = requests.get(
            self.fonte_url, timeout=30,
            params={"UF": uf, "tipo_pessoa": "juridica", "limit": self.LIMITE_POR_PAGINA, "offset": offset},
        )
        resposta.raise_for_status()
        return resposta.json()

    def coletar(self, uf: str, max_paginas: int | None = None, **opcoes) -> Iterator[RegistroIncentivo]:
        offset, pagina = 0, 0
        while True:
            payload = self._paginador(uf, offset)
            registros = (payload.get("_embedded") or {}).get("incentivadores", [])
            if not registros:
                return
            for bruto in registros:
                normalizado = transformacao.transformar_registro(bruto, fonte_nome=self.fonte_nome)
                if normalizado is None:  # sem nome ou URL de origem: descartado, nunca completado
                    continue
                normalizado["incentivo"]["mecanismo"] = self.codigo
                yield RegistroIncentivo(normalizado["empresa"], normalizado["incentivo"])
            pagina += 1
            offset += self.LIMITE_POR_PAGINA
            total = payload.get("total")
            if (max_paginas is not None and pagina >= max_paginas) or (total is not None and offset >= total):
                return
            time.sleep(self._pausa)


class ProvedorIndisponivel(IncentivoProvider):
    """Mecanismo real, mas sem fonte pública estruturada confiável (ver INVESTIGACAO)."""

    def __init__(self, codigo: str, esfera: str, fonte_nome: str, fonte_url: str | None = None):
        self.codigo = codigo
        self.nome = ROTULOS_MECANISMO.get(codigo, codigo)
        self.esfera = esfera
        self.fonte_nome = fonte_nome
        self.fonte_url = fonte_url

    def coletar(self, uf: str, max_paginas: int | None = None, **opcoes) -> Iterator[RegistroIncentivo]:
        raise IntegracaoIndisponivel(f"Integração ainda não disponível para {self.nome}: {self.investigacao}")


def provedores_padrao() -> dict[str, IncentivoProvider]:
    provedores: list[IncentivoProvider] = [
        SalicRouanetProvider(),
        ProvedorIndisponivel(MECANISMO_LPIE, "Estadual (SP)", "Dados Abertos SP",
                             "https://dadosabertos.sp.gov.br/dataset/lei-paulista-de-incentivo-ao-esporte"),
        ProvedorIndisponivel(MECANISMO_LIE, "Federal", "Ministério do Esporte — painel de transparência",
                             "https://www.gov.br/esporte/pt-br/acoes-e-programas/lei-de-incentivo-ao-esporte"),
        ProvedorIndisponivel(MECANISMO_PROAC_ICMS, "Estadual (SP)", "Secretaria da Cultura SP — ProAC ICMS",
                             "https://www.cultura.sp.gov.br/sec_cultura/Fomento/ProAC_ICMS"),
        ProvedorIndisponivel(MECANISMO_PRONON_PRONAS, "Federal", "Ministério da Saúde",
                             "https://www.gov.br/saude/pt-br/se/pronon-e-pronas-pcd"),
        ProvedorIndisponivel(MECANISMO_FIA_IDOSO, "Municipal", "Conselhos municipais / Receita Federal (DBF)"),
    ]
    return {p.codigo: p for p in provedores}


# --------------------------------------------------------------------------- banco
def migrar(conexao: sqlite3.Connection) -> None:
    """Adiciona `mecanismo` a `incentivos` e classifica o que já existe. Idempotente e sem perda:
    só preenche linhas em que a coluna ainda está vazia, e só quando o tipo/fonte indica Rouanet."""
    colunas = {l[1] for l in conexao.execute("PRAGMA table_info(incentivos)")}
    if "mecanismo" not in colunas:
        conexao.execute("ALTER TABLE incentivos ADD COLUMN mecanismo TEXT")
    conexao.execute(
        """UPDATE incentivos SET mecanismo = ?
           WHERE mecanismo IS NULL AND (tipo_incentivo LIKE 'Lei Rouanet%' OR fonte LIKE '%Rouanet%')""",
        (MECANISMO_ROUANET,),
    )
    conexao.commit()


def ingerir(conexao: sqlite3.Connection, provider: IncentivoProvider, uf: str, max_paginas: int | None = None) -> dict:
    """Grava os registros de um provedor. Empresas: deduplicadas por CNPJ válido. Incentivos:
    deduplicados pela URL da fonte. Devolve contadores."""
    migrar(conexao)
    resumo = {"mecanismo": provider.codigo, "lidos": 0, "empresas_novas": 0, "empresas_existentes": 0,
              "incentivos_novos": 0, "incentivos_atualizados": 0}
    for registro in provider.coletar(uf, max_paginas=max_paginas):
        resumo["lidos"] += 1
        empresa_id, criada = banco.obter_ou_criar_empresa(conexao, registro.empresa)
        resumo["empresas_novas" if criada else "empresas_existentes"] += 1
        dados = {**registro.incentivo, "empresa_id": empresa_id}
        _, novo = banco.inserir_ou_atualizar_incentivo(conexao, dados)
        resumo["incentivos_novos" if novo else "incentivos_atualizados"] += 1
    conexao.commit()
    return resumo


def resumo_por_mecanismo(conexao: sqlite3.Connection) -> list[dict]:
    """Uma linha por mecanismo presente no banco: registros, empresas, valor, UFs, período."""
    migrar(conexao)
    linhas = conexao.execute(
        """SELECT COALESCE(mecanismo, 'NAO_CLASSIFICADO') AS mecanismo, COUNT(*) AS registros,
                  COUNT(DISTINCT empresa_id) AS empresas, COALESCE(SUM(valor), 0) AS valor_total,
                  GROUP_CONCAT(DISTINCT uf) AS ufs, MIN(ano) AS ano_min, MAX(ano) AS ano_max
           FROM incentivos GROUP BY 1 ORDER BY registros DESC"""
    ).fetchall()
    return [dict(l) for l in linhas]
