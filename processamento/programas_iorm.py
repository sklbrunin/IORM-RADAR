"""Quais projetos financiados "são do IORM"? — fonte única para Linha Cruzada, métricas e telas.

Problema que este módulo resolve: a lista de programas era uma constante no código
(`metricas.PROGRAMAS_IORM`) e ficou desatualizada em relação ao Cérebro da OSC. Resultado real: o
projeto "IORM CULTURAL 2026" (apoiado em 2025/2026) não estava na lista, e as empresas que o apoiaram
continuavam aparecendo como prospects. Agora os termos vêm de:

  1. a lista-base histórica (programas publicados em iorm.org.br);
  2. os programas cadastrados no Cérebro da OSC (`osc_programas`), exceto nomes genéricos demais;
  3. a sigla/nome da OSC (`osc.nome_fantasia`, `osc.nome`) — projeto que leva o nome do IORM é do IORM.

A comparação ignora acento/caixa e usa PALAVRA inteira (a sigla "iorm" não casa dentro de outra palavra).
Nada é adivinhado: projeto que não bate com nenhum termo simplesmente não conta.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata

BASE = [
    "usina da dança", "cine energia", "tramas do interior", "profissionalizando pessoas",
    "nossas bibliotecas", "cia. da dança", "companhia da dança",
]
# Nomes de programa genéricos demais: casariam com projetos de qualquer outra instituição.
GENERICOS = {"artes e cultura", "cultura", "arte", "artes", "musica", "educacao", "esporte", "projeto", "programa"}


def normalizar(texto) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento).strip()


_termos: list[str] = [normalizar(t) for t in BASE]
_padrao: re.Pattern | None = None


def _compilar() -> None:
    global _padrao
    partes = [re.escape(t) for t in sorted(set(_termos), key=len, reverse=True) if t]
    _padrao = re.compile(r"(?<![a-z0-9])(?:" + "|".join(partes) + r")(?![a-z0-9])") if partes else None


_compilar()


def termos() -> list[str]:
    return sorted(set(_termos))


def carregar(conexao: sqlite3.Connection) -> list[str]:
    """Relê os termos a partir do Cérebro da OSC (idempotente). Sem tabelas da OSC (banco de teste),
    mantém a lista-base."""
    global _termos
    novos = [normalizar(t) for t in BASE]
    try:
        for linha in conexao.execute("SELECT nome FROM osc_programas"):
            nome = normalizar(linha[0])
            if nome and nome not in GENERICOS and len(nome) >= 6:
                novos.append(nome)
        for linha in conexao.execute("SELECT nome, nome_fantasia FROM osc"):
            for campo in (linha[0], linha[1]):
                nome = normalizar(campo)
                if nome and len(nome) >= 4:
                    novos.append(nome)
    except sqlite3.OperationalError:
        pass
    _termos = novos
    _compilar()
    return termos()


def projeto_e_do_iorm(projeto) -> bool:
    if not projeto or _padrao is None:
        return False
    return bool(_padrao.search(normalizar(projeto)))


def projetos_do_iorm(projetos_concatenados) -> list[str]:
    """Trechos (separados por vírgula) de uma lista de projetos que são do IORM — para exibição."""
    if not projetos_concatenados:
        return []
    return [p.strip() for p in str(projetos_concatenados).split(",") if p.strip() and projeto_e_do_iorm(p)]


def registrar(conexao: sqlite3.Connection) -> None:
    """Atualiza os termos e expõe `eh_projeto_iorm(projeto)` como função SQL nesta conexão."""
    carregar(conexao)
    conexao.create_function("eh_projeto_iorm", 1, lambda p: int(projeto_e_do_iorm(p)))
