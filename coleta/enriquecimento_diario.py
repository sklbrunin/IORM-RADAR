"""Rotina diária de enriquecimento — meta de 30 empresas/dia.

Como rodar manualmente:
    python coleta/enriquecimento_diario.py
    python coleta/enriquecimento_diario.py --meta 5 --sem-web        (teste curto, sem gastar cota)

Como agendar no Windows (uma vez): abra o PowerShell na pasta do projeto e rode
    powershell -ExecutionPolicy Bypass -File coleta\\agendar_enriquecimento_windows.ps1
A partir daí o Agendador de Tarefas roda este script todo dia (e recupera a execução
se o computador estava desligado no horário). Ver README/docs para verificar.

O que a rotina faz e quais limites respeita: ver processamento/fila_enriquecimento.py.
Toda execução: backup do banco (1 por dia), log em dados/logs/enriquecimento_diario.log."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RAIZ_PROJETO / ".env")

from processamento import (  # noqa: E402
    banco, contact_providers, fila_enriquecimento, metricas, osc, relacionamento,
)

CAMINHO_DB = RAIZ_PROJETO / "dados" / "iorm_radar.db"
PASTA_BACKUPS = RAIZ_PROJETO / "dados" / "backups"
CAMINHO_LOG = RAIZ_PROJETO / "dados" / "logs" / "enriquecimento_diario.log"


def backup_do_dia() -> Path | None:
    """Um backup por dia, antes de qualquer gravação. Devolve o caminho (ou None se já existia)."""
    PASTA_BACKUPS.mkdir(parents=True, exist_ok=True)
    dia = datetime.now().strftime("%Y%m%d")
    if any(PASTA_BACKUPS.glob(f"iorm_radar_{dia}_*_pre_rotina.db")):
        return None
    destino = PASTA_BACKUPS / f"iorm_radar_{dia}_{datetime.now().strftime('%H%M%S')}_pre_rotina.db"
    shutil.copy2(CAMINHO_DB, destino)
    return destino


def carregar_df(conexao):
    principal = osc.obter_osc_principal(conexao)
    perfil = osc.carregar_perfil_completo(conexao, principal["id"]) if principal else None
    df = metricas.carregar_empresas(conexao, perfil["cidades"] if perfil else None, perfil["territorios"] if perfil else None)
    return metricas.mesclar_empresas_e_enriquecimento(df, metricas.carregar_enriquecimento(conexao))


def main() -> int:
    parser = argparse.ArgumentParser(description="Enriquecimento diário de empresas (meta configurável).")
    parser.add_argument("--meta", type=int, default=fila_enriquecimento.META_PADRAO)
    parser.add_argument("--somente-regiao", action="store_true", help="Não completa a meta com empresas de fora da Região IORM.")
    parser.add_argument("--sem-web", action="store_true", help="Não usa a busca web (não gasta cota da SerpApi).")
    parser.add_argument("--pausa", type=float, default=1.0, help="Segundos entre empresas (respeito a limites de API).")
    parser.add_argument("--agendada", action="store_true", help="Marca a execução como vinda do Agendador de Tarefas.")
    args = parser.parse_args()

    if not CAMINHO_DB.exists():
        print("Banco de dados não encontrado — rode a coleta primeiro.")
        return 2
    backup = backup_do_dia()
    conexao = banco.conectar(CAMINHO_DB)
    banco.migrar_empresas(conexao)
    fila_enriquecimento.criar_tabelas(conexao)
    relacionamento.sincronizar(conexao)

    providers = [contact_providers.ReceitaFederalContactProvider()]
    if not args.sem_web:
        providers.append(contact_providers.WebSearchContactProvider(conexao))
    providers.append(contact_providers.HunterContactProvider())  # só age com HUNTER_API_KEY e site conhecido

    resumo = fila_enriquecimento.executar(
        conexao, carregar_df(conexao), providers, meta=args.meta,
        origem="AGENDADA" if args.agendada else "MANUAL",
        incluir_fora_da_regiao=not args.somente_regiao, pausa_entre_empresas=args.pausa,
    )
    conexao.close()

    CAMINHO_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CAMINHO_LOG.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps({"em": datetime.now(timezone.utc).isoformat(), "backup": str(backup) if backup else None, **resumo},
                                 ensure_ascii=False) + "\n")

    print(f"Execução #{resumo['execucao_id']}: {resumo['processadas']} empresa(s) — "
          f"{resumo['sucesso']} sucesso, {resumo['parcial']} parcial, {resumo['falha']} falha "
          f"({resumo['chamadas_serpapi']} chamada(s) SerpApi).")
    if resumo["observacao"]:
        print(resumo["observacao"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
