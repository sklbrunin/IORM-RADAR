"""Coleta incentivos de QUALQUER mecanismo registrado em processamento/incentivos_providers.py.

    python coleta/coleta_incentivos.py --listar
    python coleta/coleta_incentivos.py --mecanismo LEI_ROUANET --uf MG --max-paginas 2

Mecanismos sem fonte pública estruturada confiável não coletam nada: o comando explica por quê
(resultado da investigação de fontes) em vez de inventar dado.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from processamento import banco, incentivos_providers  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta incentivos por mecanismo.")
    parser.add_argument("--listar", action="store_true", help="Lista os mecanismos e o estado de integração de cada um.")
    parser.add_argument("--mecanismo", default=incentivos_providers.MECANISMO_ROUANET)
    parser.add_argument("--uf", default="SP")
    parser.add_argument("--max-paginas", type=int, default=None)
    args = parser.parse_args()

    provedores = incentivos_providers.provedores_padrao()
    if args.listar:
        for codigo, p in provedores.items():
            print(f"{codigo:20} {p.status:12} {p.nome}\n{'':34}{p.investigacao}")
        return 0

    provider = provedores.get(args.mecanismo)
    if provider is None:
        print(f"Mecanismo desconhecido: {args.mecanismo}. Use --listar.")
        return 2

    conexao = banco.conectar(RAIZ_PROJETO / "dados" / "iorm_radar.db")
    banco.criar_tabelas(conexao)
    try:
        resumo = incentivos_providers.ingerir(conexao, provider, args.uf, args.max_paginas)
    except incentivos_providers.IntegracaoIndisponivel as exc:
        print(str(exc))
        return 1
    finally:
        conexao.close()
    print(resumo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
