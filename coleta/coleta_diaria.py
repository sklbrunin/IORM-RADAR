"""Rotina de descoberta diária de novas empresas — meta de ~30 empresas
NOVAS por execução (pode ser menos, se as fontes não tiverem mais dados
disponíveis; nunca inventa registro pra "bater a meta").

Fonte real e já integrada: API do SALIC (Lei Rouanet) — a mesma usada por
coleta/coleta_salic.py, só que aqui percorrendo estado por estado, com
memória de onde parou (dados/estado_coleta_diaria.json), para nunca
recomeçar do zero nem repetir chamada desnecessária à API.

IMPORTANTE — honestidade sobre execução automática: este processo NÃO
roda sozinho 24/7 neste ambiente (é um script Python comum, precisa de
algo para chamá-lo). Está pronto para ser agendado via Windows Task
Scheduler — ver docs/decisoes.md e o comentário no fim deste arquivo para
o passo a passo exato de como ativar isso.

Como rodar manualmente:
    python coleta/coleta_diaria.py
    python coleta/coleta_diaria.py --meta 30 --max-paginas-por-uf 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from coleta import coleta_salic  # noqa: E402
from processamento import banco, transformacao  # noqa: E402

CAMINHO_ESTADO = RAIZ_PROJETO / "dados" / "estado_coleta_diaria.json"
CAMINHO_LOG = RAIZ_PROJETO / "dados" / "logs" / "coleta_diaria.log"

# Ordem em que os estados são percorridos — todos reais (códigos oficiais
# de UF), sem nenhuma empresa ou dado inventado; a ordem prioriza SP (onde
# o IORM atua) e estados vizinhos/relevantes para expansão futura.
UFS_PADRAO = ["SP", "MG", "PR", "RJ", "MT", "GO"]

META_PADRAO_EMPRESAS_NOVAS = 30
MAX_PAGINAS_POR_UF_PADRAO = 10  # limite de segurança por UF numa única execução


def _carregar_estado(caminho: Path = CAMINHO_ESTADO) -> dict:
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def _salvar_estado(estado: dict, caminho: Path = CAMINHO_ESTADO) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def _registrar_log(linha: dict, caminho: Path = CAMINHO_LOG) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")


def executar(meta_empresas_novas: int = META_PADRAO_EMPRESAS_NOVAS,
             max_paginas_por_uf: int = MAX_PAGINAS_POR_UF_PADRAO,
             ufs: list[str] | None = None,
             caminho_db: Path | None = None,
             caminho_estado: Path | None = None,
             caminho_log: Path | None = None) -> dict:
    """Percorre UFs (retomando de onde parou) até atingir a meta de
    empresas novas ou esgotar o limite de páginas/UFs desta execução.
    Nunca duplica (dedup por CNPJ já é feito por banco.obter_ou_criar_empresa)
    e nunca inventa registro. `caminho_db`/`caminho_estado`/`caminho_log`
    só existem para os testes automatizados injetarem caminhos temporários
    — em uso normal, sempre os caminhos padrão do projeto."""
    ufs = ufs or UFS_PADRAO
    caminho_estado = caminho_estado or CAMINHO_ESTADO
    caminho_log = caminho_log or CAMINHO_LOG
    estado = _carregar_estado(caminho_estado)
    inicio = datetime.now(timezone.utc)

    caminho_db = caminho_db or (RAIZ_PROJETO / "dados" / "iorm_radar.db")
    conexao = banco.conectar(caminho_db)
    banco.criar_tabelas(conexao)

    resumo_execucao = {
        "iniciado_em": inicio.isoformat(),
        "meta_empresas_novas": meta_empresas_novas,
        "ufs_processadas": [],
        "empresas_novas_total": 0,
        "empresas_existentes_total": 0,
        "registros_lidos_total": 0,
        "registros_descartados_total": 0,
        "erros": [],
    }

    total_novas_execucao = 0

    for uf in ufs:
        if total_novas_execucao >= meta_empresas_novas:
            break

        estado_uf = estado.get(uf, {"offset": 0, "concluido": False})
        if estado_uf.get("concluido"):
            continue  # já coletamos tudo que a API tinha pra esse UF

        offset = estado_uf["offset"]
        paginas_nesta_uf = 0
        resumo_uf = {"uf": uf, "registros_lidos": 0, "empresas_novas": 0, "empresas_existentes": 0, "descartados": 0}

        try:
            while total_novas_execucao < meta_empresas_novas and paginas_nesta_uf < max_paginas_por_uf:
                payload = coleta_salic.buscar_pagina(uf=uf, offset=offset)
                total_api = payload.get("total")
                registros = payload.get("_embedded", {}).get("incentivadores", [])
                if not registros:
                    estado_uf["concluido"] = True
                    break

                for bruto in registros:
                    resumo_uf["registros_lidos"] += 1
                    resultado = transformacao.transformar_registro(bruto, fonte_nome=coleta_salic.FONTE_NOME)
                    if resultado is None:
                        resumo_uf["descartados"] += 1
                        continue
                    empresa_id, criada = banco.obter_ou_criar_empresa(conexao, resultado["empresa"])
                    if criada:
                        resumo_uf["empresas_novas"] += 1
                        total_novas_execucao += 1
                    else:
                        resumo_uf["empresas_existentes"] += 1
                    dados_incentivo = resultado["incentivo"]
                    dados_incentivo["empresa_id"] = empresa_id
                    banco.inserir_ou_atualizar_incentivo(conexao, dados_incentivo)

                conexao.commit()
                offset += coleta_salic.LIMITE_POR_PAGINA
                paginas_nesta_uf += 1
                if total_api is not None and offset >= total_api:
                    estado_uf["concluido"] = True
                    break
                if total_novas_execucao >= meta_empresas_novas:
                    break
                time.sleep(coleta_salic.PAUSA_ENTRE_CHAMADAS_SEGUNDOS)
        except Exception as exc:  # nunca deixa uma falha de rede derrubar a rotina inteira
            resumo_execucao["erros"].append(f"{uf}: {exc}")

        estado_uf["offset"] = offset
        estado[uf] = estado_uf
        resumo_execucao["ufs_processadas"].append(resumo_uf)
        resumo_execucao["empresas_novas_total"] = sum(u["empresas_novas"] for u in resumo_execucao["ufs_processadas"])
        resumo_execucao["empresas_existentes_total"] = sum(u["empresas_existentes"] for u in resumo_execucao["ufs_processadas"])
        resumo_execucao["registros_lidos_total"] = sum(u["registros_lidos"] for u in resumo_execucao["ufs_processadas"])
        resumo_execucao["registros_descartados_total"] = sum(u["descartados"] for u in resumo_execucao["ufs_processadas"])

    _salvar_estado(estado, caminho_estado)
    conexao.close()

    resumo_execucao["finalizado_em"] = datetime.now(timezone.utc).isoformat()
    _registrar_log(resumo_execucao, caminho_log)
    return resumo_execucao


def main():
    parser = argparse.ArgumentParser(description="Descoberta diária de novas empresas via SALIC (meta configurável).")
    parser.add_argument("--meta", type=int, default=META_PADRAO_EMPRESAS_NOVAS, help="Meta de empresas novas nesta execução.")
    parser.add_argument("--max-paginas-por-uf", type=int, default=MAX_PAGINAS_POR_UF_PADRAO)
    parser.add_argument("--ufs", nargs="+", default=None, help="Lista de UFs a considerar, em ordem (padrão: SP MG PR RJ MT GO).")
    args = parser.parse_args()

    print(f"Iniciando descoberta diária (meta: {args.meta} empresa(s) nova(s))...")
    resumo = executar(meta_empresas_novas=args.meta, max_paginas_por_uf=args.max_paginas_por_uf, ufs=args.ufs)
    print(f"\nConcluído: {resumo['empresas_novas_total']} empresa(s) nova(s), "
          f"{resumo['empresas_existentes_total']} já existente(s), "
          f"{resumo['registros_descartados_total']} descartada(s) (dado insuficiente).")
    if resumo["erros"]:
        print(f"Erros: {resumo['erros']}")
    print(f"Log completo em: {CAMINHO_LOG}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------
# COMO AGENDAR ESTA ROTINA (Windows Task Scheduler) — não roda sozinha
# 24/7 neste ambiente; precisa ser agendada pelo próprio computador/servidor.
#
# 1. Abra "Agendador de Tarefas" (Task Scheduler) no Windows.
# 2. "Criar Tarefa Básica..." -> nome: "IORM Radar - Descoberta Diária".
# 3. Gatilho: Diariamente, no horário desejado (ex: 6h da manhã).
# 4. Ação: "Iniciar um programa".
#    Programa/script:  python
#    Argumentos:        coleta\coleta_diaria.py
#    Iniciar em:        C:\Users\Usuario\Desktop\Bruno\claude code\IORM - RADAR
# 5. Concluir. A tarefa passa a rodar todo dia, mesmo sem o Streamlit aberto.
# 6. Para conferir o histórico: dados/logs/coleta_diaria.log (uma linha
#    JSON por execução) e dados/estado_coleta_diaria.json (de onde cada
#    UF vai continuar na próxima vez).
# ---------------------------------------------------------------------
