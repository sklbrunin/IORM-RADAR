"""Gera um relatório simples a partir do banco já coletado.

Pode ser rodado sozinho (sem coletar nada de novo):
    python processamento/relatorio.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def imprimir_relatorio(conexao: sqlite3.Connection, resumo_execucao: dict | None = None) -> None:
    total_empresas = conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
    total_com_cnpj = conexao.execute("SELECT COUNT(*) FROM empresas WHERE cnpj IS NOT NULL").fetchone()[0]
    total_incentivos = conexao.execute("SELECT COUNT(*) FROM incentivos").fetchone()[0]
    soma_valor = conexao.execute("SELECT SUM(valor) FROM incentivos").fetchone()[0] or 0

    print("\n===== RELATÓRIO DA COLETA =====")
    if resumo_execucao:
        print(f"Registros recebidos da API nesta execução: {resumo_execucao['registros_recebidos']}")
        print(f"Registros descartados (sem nome ou sem URL de origem): {resumo_execucao['registros_descartados']}")
        print(f"Empresas novas criadas nesta execução: {resumo_execucao['empresas_novas']}")
        print(f"Empresas já existentes reaproveitadas: {resumo_execucao['empresas_existentes']}")
        print(f"Incentivos novos gravados: {resumo_execucao['incentivos_novos']}")
        print(f"Incentivos já existentes atualizados: {resumo_execucao['incentivos_atualizados']}")

    print("\n--- Totais acumulados no banco ---")
    print(f"Total de empresas no banco: {total_empresas}")
    print(f"  das quais com CNPJ validado: {total_com_cnpj}")
    print(f"  sem CNPJ confirmado: {total_empresas - total_com_cnpj}")
    print(f"Total de registros de incentivo: {total_incentivos}")
    print(f"Soma dos valores (agregados por incentivador, Lei Rouanet): R$ {soma_valor:,.2f}")

    print("\n--- Amostra de até 5 empresas gravadas ---")
    amostra = conexao.execute(
        "SELECT razao_social, cnpj, cidade, estado FROM empresas ORDER BY id DESC LIMIT 5"
    ).fetchall()
    for linha in amostra:
        cnpj_exibicao = linha["cnpj"] or "não disponível"
        print(f"- {linha['razao_social']} | CNPJ: {cnpj_exibicao} | {linha['cidade']}/{linha['estado']}")
    print("================================\n")


if __name__ == "__main__":
    raiz_projeto = Path(__file__).resolve().parent.parent
    caminho_db = raiz_projeto / "dados" / "iorm_radar.db"
    if not caminho_db.exists():
        print(f"Banco ainda não existe em {caminho_db}. Rode a coleta primeiro:")
        print("  python coleta/coleta_salic.py")
    else:
        conexao = sqlite3.connect(caminho_db)
        conexao.row_factory = sqlite3.Row
        imprimir_relatorio(conexao)
        conexao.close()
