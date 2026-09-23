"""Coleta os "incentivadores" (empresas que doaram via Lei Rouanet) da API
pública do SALIC (Ministério da Cultura) para um estado (UF) escolhido.

Fluxo: chama a API -> salva a resposta bruta em dados/brutos/ -> transforma
e valida os dados -> grava no banco SQLite -> imprime um relatório simples.

Fonte oficial: https://api.salic.cultura.gov.br/docs

Como rodar:
    python coleta/coleta_salic.py --uf SP
    python coleta/coleta_salic.py --uf SP --max-paginas 3   (teste rápido)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from processamento import banco, relacionamento, relatorio, transformacao  # noqa: E402

BASE_URL = "https://api.salic.cultura.gov.br/api/v1/incentivadores"
FONTE_NOME = "SALIC - Sistema de Apoio às Leis de Incentivo à Cultura (Lei Rouanet)"
FONTE_TIPO = "API pública oficial (Ministério da Cultura / Secretaria Especial da Cultura)"
LIMITE_POR_PAGINA = 100
PAUSA_ENTRE_CHAMADAS_SEGUNDOS = 0.3


def buscar_pagina(uf: str, offset: int, tipo_pessoa: str = "juridica") -> dict:
    parametros = {
        "UF": uf,
        "tipo_pessoa": tipo_pessoa,
        "limit": LIMITE_POR_PAGINA,
        "offset": offset,
    }
    resposta = requests.get(BASE_URL, params=parametros, timeout=30)
    resposta.raise_for_status()
    return resposta.json()


def salvar_bruto(payload: dict, pasta_execucao: Path, offset: int) -> Path:
    pasta_execucao.mkdir(parents=True, exist_ok=True)
    caminho = pasta_execucao / f"pagina_offset_{offset:06d}.json"
    caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def coletar(uf: str, max_paginas: int | None, conexao) -> dict:
    """Percorre as páginas da API para o UF informado e grava no banco.
    Devolve um resumo com contadores para o relatório final."""
    timestamp_execucao = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pasta_execucao = RAIZ_PROJETO / "dados" / "brutos" / "salic" / f"{uf}_{timestamp_execucao}"

    offset = 0
    pagina_num = 0
    total_registros_api = None
    resumo = {
        "registros_recebidos": 0,
        "empresas_novas": 0,
        "empresas_existentes": 0,
        "incentivos_novos": 0,
        "incentivos_atualizados": 0,
        "registros_descartados": 0,
    }

    while True:
        payload = buscar_pagina(uf=uf, offset=offset)
        salvar_bruto(payload, pasta_execucao, offset)

        if total_registros_api is None:
            total_registros_api = payload.get("total")
            print(f"A API informa um total de {total_registros_api} incentivadores para UF={uf} (pessoa jurídica).")

        registros = payload.get("_embedded", {}).get("incentivadores", [])
        if not registros:
            break

        for bruto in registros:
            resumo["registros_recebidos"] += 1
            resultado = transformacao.transformar_registro(bruto, fonte_nome=FONTE_NOME)

            if resultado is None:
                resumo["registros_descartados"] += 1
                continue

            dados_empresa = resultado["empresa"]
            dados_incentivo = resultado["incentivo"]

            empresa_id, empresa_criada = banco.obter_ou_criar_empresa(conexao, dados_empresa)
            resumo["empresas_novas" if empresa_criada else "empresas_existentes"] += 1

            dados_incentivo["empresa_id"] = empresa_id
            _, incentivo_criado = banco.inserir_ou_atualizar_incentivo(conexao, dados_incentivo)
            resumo["incentivos_novos" if incentivo_criado else "incentivos_atualizados"] += 1

        conexao.commit()
        pagina_num += 1
        offset += LIMITE_POR_PAGINA

        print(
            f"Página {pagina_num} processada. "
            f"{resumo['registros_recebidos']} registros lidos até agora."
        )

        if max_paginas is not None and pagina_num >= max_paginas:
            print(f"Limite de {max_paginas} página(s) atingido (--max-paginas). Parando de propósito.")
            break

        if total_registros_api is not None and offset >= total_registros_api:
            break

        time.sleep(PAUSA_ENTRE_CHAMADAS_SEGUNDOS)

    banco.registrar_fonte(
        conexao,
        {
            "nome": FONTE_NOME,
            "url": BASE_URL,
            "tipo": FONTE_TIPO,
            "coletado_em": datetime.now(timezone.utc).isoformat(),
        },
    )
    conexao.commit()
    # Incentivos novos podem tornar empresas "apoiadoras do IORM": reconcilia a Linha Cruzada.
    relacionamento.reconciliar_relacionamentos(conexao)
    return resumo


def main():
    parser = argparse.ArgumentParser(description="Coleta incentivadores da Lei Rouanet (SALIC) para um estado.")
    parser.add_argument("--uf", default="SP", help="Sigla do estado (padrão: SP)")
    parser.add_argument(
        "--max-paginas",
        type=int,
        default=None,
        help="Limita o número de páginas buscadas (útil para testes rápidos, ex: --max-paginas 3).",
    )
    args = parser.parse_args()

    caminho_db = RAIZ_PROJETO / "dados" / "iorm_radar.db"
    conexao = banco.conectar(caminho_db)
    banco.criar_tabelas(conexao)

    print(f"Iniciando coleta do SALIC para UF={args.uf}...\n")
    resumo = coletar(uf=args.uf, max_paginas=args.max_paginas, conexao=conexao)

    print("\nColeta concluída.")
    relatorio.imprimir_relatorio(conexao, resumo)
    conexao.close()


if __name__ == "__main__":
    main()
