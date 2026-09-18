"""Camada regional: POLOS do IORM -> cidades da região de cada polo.

METODOLOGIA (documentada também em docs/decisoes.md):
  "Região de um polo" = todos os municípios da mesma REGIÃO GEOGRÁFICA
  IMEDIATA do IBGE (divisão regional oficial de 2017, que agrupa
  municípios em torno de um centro urbano e dos fluxos do dia a dia:
  trabalho, comércio, serviços). Fonte: API pública de Localidades do
  IBGE (https://servicodados.ibge.gov.br/api/v1/localidades). Nenhuma
  cidade é escolhida "de cabeça" — a lista vem do IBGE, e cada linha
  guarda fonte, código IBGE e data.

  Os polos (Ipuã, Guaíra, Miguelópolis, Orlândia) continuam sendo os
  cadastrados em Cérebro da OSC (osc_territorios, tipo 'cidade').

EDITÁVEL: a tabela `regiao_municipios` aceita adicionar município
manualmente a um polo (origem MANUAL) e desativar qualquer município
(inclusive vindo do IBGE) sem apagar o registro. A sincronização com o
IBGE nunca reativa o que a equipe desativou nem sobrescreve o manual.

Integração: `osc.carregar_perfil_completo` expõe os municípios ativos
como território `regiao_proxima`, o que alimenta o IORM Score, os filtros
e os radares sem mudar mais nada."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Callable

import requests

from processamento import regiao

URL_IBGE_MUNICIPIOS_UF = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_id}/municipios"
FONTE_IBGE = "IBGE — API de Localidades, Região Geográfica Imediata (divisão regional 2017)"
ORIGEM_IBGE = "IBGE_REGIAO_IMEDIATA"
ORIGEM_MANUAL = "MANUAL"

# Códigos oficiais de UF no IBGE — só as UFs já usadas pelo projeto; adicionar
# outra é acrescentar uma linha (o código é público e fixo).
CODIGO_UF = {"SP": 35, "MG": 31, "PR": 41, "RJ": 33, "MT": 51, "GO": 52}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def criar_tabelas(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS regiao_municipios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            polo TEXT NOT NULL,
            municipio TEXT NOT NULL,
            uf TEXT NOT NULL,
            ibge_id INTEGER,
            regiao_imediata TEXT,
            origem TEXT NOT NULL,
            fonte TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL,
            UNIQUE(polo, municipio, uf)
        );
        """
    )
    conexao.commit()


def buscar_regiao_ibge(polo: str, uf: str, fetcher: Callable[[str], list] | None = None) -> dict:
    """Consulta o IBGE: acha a Região Geográfica Imediata do polo e lista
    seus municípios. `fetcher(url) -> json` é injetável para teste (sem
    rede). Devolve {"regiao_imediata": nome, "municipios": [(ibge_id, nome)]}
    ou levanta ValueError se o polo não existir naquela UF."""
    fetcher = fetcher or (lambda url: requests.get(url, timeout=30).json())
    uf_id = CODIGO_UF.get(uf.upper())
    if uf_id is None:
        raise ValueError(f"UF sem código IBGE cadastrado: {uf}")
    municipios_uf = fetcher(URL_IBGE_MUNICIPIOS_UF.format(uf_id=uf_id))
    alvo = regiao.normalizar_cidade(polo)
    achado = next((m for m in municipios_uf if regiao.normalizar_cidade(m["nome"]) == alvo), None)
    if achado is None or not achado.get("regiao-imediata"):
        raise ValueError(f"Polo '{polo}/{uf}' não encontrado no IBGE.")
    ri = achado["regiao-imediata"]
    do_grupo = [
        (m["id"], m["nome"]) for m in municipios_uf
        if (m.get("regiao-imediata") or {}).get("id") == ri["id"]
    ]
    return {"regiao_imediata": ri["nome"], "municipios": sorted(do_grupo, key=lambda x: x[1])}


def sincronizar_ibge(conexao: sqlite3.Connection, polos: list[str], uf: str,
                      fetcher: Callable[[str], list] | None = None) -> dict:
    """Preenche/atualiza a região de cada polo a partir do IBGE. Não
    duplica (UNIQUE), não reativa o que a equipe desativou, não toca em
    linha MANUAL. Faz UMA consulta ao IBGE por sincronização (a lista da
    UF inteira já traz a região imediata de todos os municípios)."""
    criar_tabelas(conexao)
    fetcher = fetcher or (lambda url: requests.get(url, timeout=30).json())
    cache: dict[str, list] = {}

    def fetch_com_cache(url: str):
        if url not in cache:
            cache[url] = fetcher(url)
        return cache[url]

    resumo = {"novos": 0, "ja_existentes": 0, "erros": []}
    for polo in polos:
        try:
            dados = buscar_regiao_ibge(polo, uf, fetch_com_cache)
        except Exception as exc:  # falha de rede/polo desconhecido não derruba os demais polos
            resumo["erros"].append(f"{polo}/{uf}: {exc}")
            continue
        for ibge_id, nome in dados["municipios"]:
            if regiao.normalizar_cidade(nome) == regiao.normalizar_cidade(polo):
                continue  # o polo em si já é "Cidade de atuação"
            cursor = conexao.execute(
                """INSERT OR IGNORE INTO regiao_municipios
                   (polo, municipio, uf, ibge_id, regiao_imediata, origem, fonte, ativo, criado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (polo, nome, uf.upper(), ibge_id, dados["regiao_imediata"], ORIGEM_IBGE, FONTE_IBGE, _agora()),
            )
            resumo["novos" if cursor.rowcount else "ja_existentes"] += 1
    conexao.commit()
    return resumo


def adicionar_manual(conexao: sqlite3.Connection, polo: str, municipio: str, uf: str, motivo: str) -> None:
    criar_tabelas(conexao)
    conexao.execute(
        """INSERT INTO regiao_municipios (polo, municipio, uf, origem, fonte, ativo, criado_em)
           VALUES (?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT(polo, municipio, uf) DO UPDATE SET ativo = 1, origem = ?, fonte = ?""",
        (polo, municipio.strip(), uf.upper(), ORIGEM_MANUAL, f"Manual: {motivo}", _agora(),
         ORIGEM_MANUAL, f"Manual: {motivo}"),
    )
    conexao.commit()


def definir_ativo(conexao: sqlite3.Connection, registro_id: int, ativo: bool) -> None:
    conexao.execute("UPDATE regiao_municipios SET ativo = ? WHERE id = ?", (int(ativo), registro_id))
    conexao.commit()


def listar(conexao: sqlite3.Connection, apenas_ativos: bool = True) -> list[dict]:
    criar_tabelas(conexao)
    filtro = "WHERE ativo = 1" if apenas_ativos else ""
    return [dict(l) for l in conexao.execute(
        f"SELECT * FROM regiao_municipios {filtro} ORDER BY polo, municipio"
    ).fetchall()]


def municipios_por_polo(conexao: sqlite3.Connection, apenas_ativos: bool = True) -> dict[str, list[dict]]:
    grupos: dict[str, list[dict]] = {}
    for linha in listar(conexao, apenas_ativos):
        grupos.setdefault(linha["polo"], []).append(linha)
    return grupos


def polos_da_cidade(conexao: sqlite3.Connection, cidade: str | None, polos: list[str]) -> list[str]:
    """Polos aos quais uma cidade pertence: ela mesma, se for polo, e/ou
    o(s) polo(s) em cuja região imediata (IBGE/manual, ativa) ela está."""
    if not cidade:
        return []
    alvo = regiao.normalizar_cidade(cidade)
    encontrados = [p for p in polos if regiao.normalizar_cidade(p) == alvo]
    for linha in listar(conexao):
        if regiao.normalizar_cidade(linha["municipio"]) == alvo and linha["polo"] not in encontrados:
            encontrados.append(linha["polo"])
    return encontrados


def territorios_derivados(conexao: sqlite3.Connection) -> list[dict]:
    """Municípios ativos no formato {tipo, valor} que o resto do sistema
    já entende — entram como 'regiao_proxima'."""
    try:
        return [{"tipo": "regiao_proxima", "valor": l["municipio"], "prioritario": 0, "polo": l["polo"]}
                for l in listar(conexao)]
    except sqlite3.OperationalError:
        return []
