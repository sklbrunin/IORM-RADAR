"""Classificação de relacionamento com o IORM ("Linha Cruzada").

Regra de negócio: empresa que já tem relação comprovada com o IORM não
deve aparecer como prospect normal. A empresa NUNCA é apagada — só a
classificação (coluna `relacionamento_iorm` em `empresas`) muda, e ela
continua com histórico, contatos e evidências intactos.

Evidências que classificam automaticamente como relacionamento:
  DOACAO_PROJETO_IORM  incentivo cujo projeto bate com um programa do IORM
                        (metricas.PROGRAMAS_IORM — dado oficial do SALIC)
  CRM_GANHO            oportunidade do CRM em "Fechado — ganho"
Classificação MANUAL (a equipe decide, com justificativa) nunca é
sobrescrita pela sincronização automática.

Exceção explícita de negócio: `reabrir_prospeccao=1` (com justificativa
escrita) faz a empresa voltar a aparecer também como prospect — ex:
apoiou há muitos anos e a equipe quer reabordar."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from processamento import metricas, programas_iorm

TIPO_DOACAO = "DOACAO_PROJETO_IORM"
TIPO_CRM = "CRM_GANHO"
TIPO_MANUAL = "MANUAL"
TIPO_PROPRIA_OSC = "PROPRIA_OSC"

ROTULOS_TIPO = {
    TIPO_PROPRIA_OSC: "É a própria OSC (nunca é prospect)",
    TIPO_DOACAO: "Apoiou projeto do IORM (dado do SALIC)",
    TIPO_CRM: "Oportunidade fechada como ganha no CRM",
    TIPO_MANUAL: "Classificação manual da equipe",
}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def sincronizar(conexao: sqlite3.Connection) -> dict:
    """Marca como relacionamento as empresas com evidência nos dados
    existentes. Idempotente; não mexe em classificação MANUAL nem em
    empresas já classificadas por outra evidência mais forte. Devolve
    contagens para log/teste."""
    marcadas = {"doacao": 0, "crm": 0, "propria_osc": 0}

    # A própria OSC aparece nos dados do SALIC como proponente/incentivador: nunca é prospect.
    try:
        cnpjs_osc = [
            "".join(ch for ch in (l["cnpj"] or "") if ch.isdigit())
            for l in conexao.execute("SELECT cnpj FROM osc WHERE cnpj IS NOT NULL")
        ]
    except sqlite3.OperationalError:  # tabela `osc` inexistente (banco de teste/antigo)
        cnpjs_osc = []
    for cnpj in {c for c in cnpjs_osc if len(c) == 14}:
        cursor = conexao.execute(
            """UPDATE empresas SET relacionamento_iorm = 1, relacionamento_tipo = ?,
                   relacionamento_fonte = 'CNPJ igual ao cadastrado no Cérebro da OSC', relacionamento_em = COALESCE(relacionamento_em, ?)
               WHERE cnpj = ? AND COALESCE(relacionamento_tipo, '') != ?""",
            (TIPO_PROPRIA_OSC, _agora(), cnpj, TIPO_MANUAL),
        )
        marcadas["propria_osc"] += cursor.rowcount

    programas_iorm.registrar(conexao)  # termos atuais: lista-base + programas do Cérebro da OSC + sigla da OSC
    linhas = conexao.execute(
        """SELECT e.id, MIN(i.ano) AS primeiro, MAX(i.ano) AS ultimo, COUNT(*) AS n,
                   GROUP_CONCAT(DISTINCT i.projeto) AS projetos
            FROM empresas e JOIN incentivos i ON i.empresa_id = e.id
            WHERE eh_projeto_iorm(i.projeto) AND COALESCE(e.relacionamento_tipo, '') NOT IN (?, ?)
            GROUP BY e.id""",
        (TIPO_MANUAL, TIPO_PROPRIA_OSC),
    ).fetchall()
    for linha in linhas:
        fonte = f"SALIC: {linha['n']} doação(ões) a projeto do IORM ({linha['projetos']}), anos {linha['primeiro']}–{linha['ultimo']}"
        conexao.execute(
            """UPDATE empresas SET relacionamento_iorm = 1, relacionamento_tipo = ?,
                   relacionamento_fonte = ?, relacionamento_em = COALESCE(relacionamento_em, ?)
               WHERE id = ?""",
            (TIPO_DOACAO, fonte, _agora(), linha["id"]),
        )
        marcadas["doacao"] += 1

    try:
        ganhas = conexao.execute(
            """SELECT DISTINCT o.empresa_id FROM crm_oportunidades o
               JOIN empresas e ON e.id = o.empresa_id
               WHERE o.estagio = 'Fechado — ganho' AND o.empresa_id IS NOT NULL
                 AND o.removida_em IS NULL AND e.relacionamento_iorm = 0"""
        ).fetchall()
    except sqlite3.OperationalError:  # tabela do CRM ainda não existe (ex: banco de teste)
        ganhas = []
    for linha in ganhas:
        conexao.execute(
            """UPDATE empresas SET relacionamento_iorm = 1, relacionamento_tipo = ?,
                   relacionamento_fonte = 'Pipeline: oportunidade em "Fechado — ganho"',
                   relacionamento_em = ? WHERE id = ?""",
            (TIPO_CRM, _agora(), linha["empresa_id"]),
        )
        marcadas["crm"] += 1

    conexao.commit()
    return marcadas


def reconciliar_relacionamentos(conexao: sqlite3.Connection) -> dict:
    """Reconcilia a classificação persistida com os dados ATUAIS e devolve o que mudou.

    Chame sempre que entrarem incentivos novos, quando os programas do Cérebro da OSC mudarem e antes de
    relatórios. Idempotente; preserva classificação MANUAL e a reabertura explícita de prospecção; não
    apaga nada. Só passa empresa de "prospect" para "relacionamento" quando há evidência nos dados."""
    antes = {l["id"]: l["relacionamento_iorm"] for l in conexao.execute("SELECT id, relacionamento_iorm FROM empresas")}
    contagens = sincronizar(conexao)
    mudaram = []
    for l in conexao.execute(
        "SELECT id, razao_social, cidade, relacionamento_iorm, relacionamento_tipo, relacionamento_fonte FROM empresas WHERE relacionamento_iorm = 1"
    ):
        if not antes.get(l["id"]):
            mudaram.append({"id": l["id"], "empresa": l["razao_social"], "cidade": l["cidade"],
                            "tipo": l["relacionamento_tipo"], "evidencia": l["relacionamento_fonte"]})
    total = conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
    rel = conexao.execute("SELECT COUNT(*) FROM empresas WHERE relacionamento_iorm = 1").fetchone()[0]
    return {"marcadas": contagens, "novas_no_relacionamento": mudaram, "empresas": total,
            "relacionamento_antes": sum(1 for v in antes.values() if v), "relacionamento_depois": rel}


def marcar_manual(conexao: sqlite3.Connection, empresa_id: int, relacionada: bool, justificativa: str) -> None:
    if not justificativa.strip():
        raise ValueError("Justificativa é obrigatória para classificar manualmente.")
    conexao.execute(
        """UPDATE empresas SET relacionamento_iorm = ?, relacionamento_tipo = ?, relacionamento_fonte = ?,
               relacionamento_em = ? WHERE id = ?""",
        (int(relacionada), TIPO_MANUAL, f"Manual: {justificativa.strip()}", _agora(), empresa_id),
    )
    conexao.commit()


def reabrir_prospeccao(conexao: sqlite3.Connection, empresa_id: int, reabrir: bool, justificativa: str | None) -> None:
    if reabrir and not (justificativa or "").strip():
        raise ValueError("Reabrir a prospecção de uma empresa com relacionamento exige justificativa explícita.")
    conexao.execute(
        "UPDATE empresas SET reabrir_prospeccao = ?, reabrir_justificativa = ? WHERE id = ?",
        (int(reabrir), (justificativa or "").strip() or None, empresa_id),
    )
    conexao.commit()


def eh_prospect(relacionamento_iorm, reabrir_prospeccao) -> bool:
    """Única definição de "prospect" do sistema: sem relacionamento, ou
    relacionamento com reabertura explícita e justificada."""
    return (not bool(relacionamento_iorm)) or bool(reabrir_prospeccao)
