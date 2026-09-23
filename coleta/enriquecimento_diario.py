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
    banco, contact_providers, descoberta_empresas, fila_enriquecimento, metricas, osc, relacionamento, rotina_etapas,
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
    parser.add_argument("--sem-descoberta", action="store_true", help="Pula a etapa de descoberta de empresas novas.")
    parser.add_argument("--novas", type=int, default=None, help="Meta de empresas NOVAS na descoberta (padrão: EMPRESAS_NOVAS_POR_DIA, 50).")
    parser.add_argument("--com-editais", action="store_true", help="Inclui a etapa de busca de editais (gasta cota da SerpApi).")
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

    principal = osc.obter_osc_principal(conexao)
    perfil = osc.carregar_perfil_completo(conexao, principal["id"]) if principal else {"cidades": [], "estados": [], "territorios": []}
    origem = "AGENDADA" if args.agendada else "MANUAL"

    def buscar_editais():
        from processamento import busca_editais, busca_providers

        return busca_editais.executar_busca(conexao, perfil, busca_providers.obter_provider_ativo())

    resumo_etapas = rotina_etapas.executar_rotina(
        conexao, perfil=perfil, carregar_df=lambda: carregar_df(conexao),
        providers_descoberta=descoberta_empresas.providers_padrao(), providers_contato=providers,
        meta_descoberta=args.novas, meta_enriquecimento=args.meta, incluir_fora_da_regiao=not args.somente_regiao,
        pausa=args.pausa, com_descoberta=not args.sem_descoberta, com_editais=args.com_editais, buscar_editais=buscar_editais,
        origem=origem,
    )
    etapas = rotina_etapas.etapas_do_dia(conexao)
    conexao.close()

    CAMINHO_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CAMINHO_LOG.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps({"em": datetime.now(timezone.utc).isoformat(), "backup": str(backup) if backup else None,
                                  "etapas": {e["etapa"]: e["status"] for e in etapas}}, ensure_ascii=False) + "\n")

    for e in etapas:
        print(f"[{e['etapa']}] {rotina_etapas.ROTULOS_STATUS[e['status']]} — {e['detalhe']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
