"""Busca, para empresas já coletadas com CNPJ confirmado, o detalhamento
por projeto/ano das doações via Lei Rouanet (endpoint /doacoes do SALIC).

Descoberta importante ao testar a API na prática: o link "_links.doacoes"
que vem na listagem de /incentivadores usa um identificador que não
funciona (deu 404 em todos os casos testados). O jeito que funciona de
verdade é chamar /api/v1/incentivadores/{CNPJ}/doacoes usando o CNPJ
diretamente como identificador. Ver docs/decisoes.md para mais detalhes.

Quando uma empresa ganha detalhamento por projeto/ano, o registro antigo
"agregado" (projeto/ano NULL, criado na etapa anterior) é removido, para
não contar o valor da empresa em dobro nos relatórios.

Como rodar:
    python coleta/coleta_salic_doacoes.py --max-empresas 20
    python coleta/coleta_salic_doacoes.py --cidades "Ipuã,Guaíra,Miguelópolis,Orlândia"
    python coleta/coleta_salic_doacoes.py                       (todas as empresas com CNPJ - demorado)
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

from processamento import banco, relacionamento, transformacao  # noqa: E402

BASE_URL = "https://api.salic.cultura.gov.br/api/v1/incentivadores"
FONTE_NOME = "SALIC - Lei Rouanet (detalhamento por doação individual)"
PAUSA_ENTRE_CHAMADAS_SEGUNDOS = 0.3


def salvar_bruto(payload: dict, pasta_execucao: Path, cnpj: str) -> None:
    pasta_execucao.mkdir(parents=True, exist_ok=True)
    caminho = pasta_execucao / f"doacoes_{cnpj}.json"
    caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def processar_empresa(conexao, empresa_row, pasta_execucao: Path) -> dict:
    """Busca as doações de uma empresa e grava no banco.
    Devolve um pequeno resumo do que aconteceu com essa empresa."""
    cnpj = empresa_row["cnpj"]
    url_doacoes = f"{BASE_URL}/{cnpj}/doacoes"
    resposta = requests.get(url_doacoes, timeout=30)

    if resposta.status_code == 404:
        return {"status": "sem_detalhamento"}

    resposta.raise_for_status()
    payload = resposta.json()
    salvar_bruto(payload, pasta_execucao, cnpj)

    doacoes_brutas = payload.get("_embedded", {}).get("doacoes", [])
    if not doacoes_brutas:
        return {"status": "sem_detalhamento"}

    linhas_gravadas = 0
    for bruto in doacoes_brutas:
        incentivo = transformacao.transformar_doacao(bruto, url_doacoes, FONTE_NOME)
        if incentivo is None:
            continue
        incentivo["empresa_id"] = empresa_row["id"]
        incentivo["uf"] = empresa_row["estado"]
        incentivo["cidade"] = empresa_row["cidade"]
        incentivo["coletado_em"] = datetime.now(timezone.utc).isoformat()
        banco.inserir_ou_atualizar_incentivo(conexao, incentivo)
        linhas_gravadas += 1

    if linhas_gravadas > 0:
        conexao.execute(
            "DELETE FROM incentivos WHERE empresa_id = ? AND projeto IS NULL AND ano IS NULL",
            (empresa_row["id"],),
        )

    return {"status": "detalhado", "doacoes": linhas_gravadas}


def main():
    parser = argparse.ArgumentParser(description="Detalha por projeto/ano as doações Lei Rouanet já coletadas.")
    parser.add_argument("--cidades", default=None, help="Lista de cidades separadas por vírgula (filtro opcional).")
    parser.add_argument("--max-empresas", type=int, default=None, help="Limita quantas empresas processar (teste rápido).")
    args = parser.parse_args()

    caminho_db = RAIZ_PROJETO / "dados" / "iorm_radar.db"
    conexao = banco.conectar(caminho_db)

    consulta = "SELECT id, cnpj, estado, cidade FROM empresas WHERE cnpj IS NOT NULL"
    parametros: list = []
    if args.cidades:
        cidades = [c.strip() for c in args.cidades.split(",")]
        marcadores = ",".join("?" for _ in cidades)
        consulta += f" AND cidade IN ({marcadores})"
        parametros.extend(cidades)

    empresas = conexao.execute(consulta, parametros).fetchall()
    if args.max_empresas is not None:
        empresas = empresas[: args.max_empresas]

    print(f"Processando doações detalhadas de {len(empresas)} empresa(s)...\n")

    timestamp_execucao = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pasta_execucao = RAIZ_PROJETO / "dados" / "brutos" / "salic_doacoes" / timestamp_execucao

    resumo = {"detalhadas": 0, "sem_detalhamento": 0, "total_doacoes_gravadas": 0}

    for indice, empresa in enumerate(empresas, start=1):
        resultado = processar_empresa(conexao, empresa, pasta_execucao)
        if resultado["status"] == "detalhado":
            resumo["detalhadas"] += 1
            resumo["total_doacoes_gravadas"] += resultado["doacoes"]
        else:
            resumo["sem_detalhamento"] += 1

        conexao.commit()

        if indice % 25 == 0 or indice == len(empresas):
            print(
                f"[{indice}/{len(empresas)}] empresas processadas "
                f"({resumo['detalhadas']} com detalhamento, {resumo['sem_detalhamento']} sem)"
            )

        time.sleep(PAUSA_ENTRE_CHAMADAS_SEGUNDOS)

    banco.registrar_fonte(
        conexao,
        {
            "nome": FONTE_NOME,
            "url": f"{BASE_URL}/{{cnpj}}/doacoes",
            "tipo": "API pública oficial (Ministério da Cultura / Secretaria Especial da Cultura)",
            "coletado_em": datetime.now(timezone.utc).isoformat(),
        },
    )
    conexao.commit()
    # Incentivos novos podem tornar empresas "apoiadoras do IORM": reconcilia a Linha Cruzada.
    relacionamento.reconciliar_relacionamentos(conexao)

    print("\nDetalhamento concluído.")
    print(f"Empresas com detalhamento por projeto/ano encontrado: {resumo['detalhadas']}")
    print(f"Empresas sem detalhamento disponível na API: {resumo['sem_detalhamento']}")
    print(f"Total de registros de doação individual gravados: {resumo['total_doacoes_gravadas']}")

    conexao.close()


if __name__ == "__main__":
    main()
