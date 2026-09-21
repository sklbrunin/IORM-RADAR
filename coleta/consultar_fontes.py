"""Consulta as Fontes de Dados cadastradas em Configurações → Fontes de Dados que estão vencidas.

    python coleta/consultar_fontes.py            # só as ativas e vencidas
    python coleta/consultar_fontes.py --todas    # todas as ativas, agora

Só fontes com método de acesso automático real (feed RSS/Atom) geram registros; as demais apenas
registram o resultado da consulta ("consulta manual", "página pública"...).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from processamento import banco, editais, fontes_dados  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--todas", action="store_true")
    args = parser.parse_args()

    conexao = banco.conectar(RAIZ_PROJETO / "dados" / "iorm_radar.db")
    editais.criar_tabelas(conexao)
    fontes_dados.criar_tabelas(conexao)
    if args.todas:
        resultados = [fontes_dados.coletar_fonte(conexao, f["id"]) for f in fontes_dados.listar(conexao, somente_ativas=True)]
    else:
        resultados = fontes_dados.coletar_devidas(conexao)
    conexao.close()
    if not resultados:
        print("Nenhuma fonte ativa com consulta vencida.")
    for r in resultados:
        print(f"- {r['fonte']}: {r['mensagem']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
