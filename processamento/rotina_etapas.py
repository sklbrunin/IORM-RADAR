"""Rotina diária em ETAPAS (v9): Descoberta → Enriquecimento → Contatos → Editais.

Cada etapa tem status próprio, gravado em `rotina_etapas` (uma linha por dia e etapa) para a página "Rotina diária" mostrar a verdade:
    PENDENTE · EXECUTANDO · CONCLUIDO · PARCIAL · SEM_COTA · FALHOU
Uma etapa que falha não derruba as demais. Descoberta (achar empresas novas) e Enriquecimento (completar dados das que já existem)
são etapas SEPARADAS de propósito: descobrir não gasta a cota de enriquecimento e vice-versa.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Callable

from processamento import descoberta_empresas, fila_enriquecimento

ETAPAS = ("Descoberta", "Enriquecimento", "Contatos", "Editais")
PENDENTE, EXECUTANDO, CONCLUIDO, PARCIAL, SEM_COTA, FALHOU = "PENDENTE", "EXECUTANDO", "CONCLUIDO", "PARCIAL", "SEM_COTA", "FALHOU"
ROTULOS_STATUS = {PENDENTE: "⏳ Pendente", EXECUTANDO: "▶ Executando", CONCLUIDO: "✅ Concluído", PARCIAL: "🟡 Parcial",
                  SEM_COTA: "🟠 Sem cota", FALHOU: "🔴 Falhou"}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def registrar_etapa(conexao: sqlite3.Connection, etapa: str, status: str, detalhe: str = "", resumo: dict | None = None,
                    data: str | None = None) -> None:
    descoberta_empresas.criar_tabelas(conexao)
    data = data or _agora().strftime("%Y-%m-%d")
    agora = _agora().isoformat()
    existente = conexao.execute("SELECT iniciado_em FROM rotina_etapas WHERE data = ? AND etapa = ?", (data, etapa)).fetchone()
    final = agora if status in (CONCLUIDO, PARCIAL, SEM_COTA, FALHOU) else None
    conexao.execute(
        """INSERT INTO rotina_etapas (data, etapa, status, iniciado_em, finalizado_em, detalhe, resumo_json) VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (data, etapa) DO UPDATE SET status = excluded.status, finalizado_em = excluded.finalizado_em,
               detalhe = excluded.detalhe, resumo_json = excluded.resumo_json,
               iniciado_em = COALESCE(rotina_etapas.iniciado_em, excluded.iniciado_em)""",
        (data, etapa, status, existente[0] if existente and existente[0] else agora, final, detalhe,
         json.dumps(resumo, ensure_ascii=False, default=str) if resumo else None))
    conexao.commit()


def etapas_do_dia(conexao: sqlite3.Connection, data: str | None = None) -> list[dict]:
    """As quatro etapas do dia, na ordem; as que ainda não rodaram aparecem como PENDENTE."""
    descoberta_empresas.criar_tabelas(conexao)
    data = data or _agora().strftime("%Y-%m-%d")
    gravadas = {l[0]: l for l in conexao.execute(
        "SELECT etapa, status, iniciado_em, finalizado_em, detalhe, resumo_json FROM rotina_etapas WHERE data = ?", (data,))}
    saida = []
    for etapa in ETAPAS:
        l = gravadas.get(etapa)
        saida.append({"etapa": etapa, "status": l[1] if l else PENDENTE, "iniciado_em": l[2] if l else None,
                      "finalizado_em": l[3] if l else None, "detalhe": (l[4] if l else "") or "",
                      "resumo": json.loads(l[5]) if l and l[5] else None})
    return saida


def _status_enriquecimento(resumo: dict, orcamento_web: int) -> tuple[str, str]:
    processadas = resumo["processadas"]
    if processadas == 0:
        return CONCLUIDO, resumo["observacao"] or "Nenhuma empresa elegível na fila."
    if resumo["falha"] == processadas:
        return FALHOU, f"{processadas} empresa(s) tentadas; todas falharam."
    if resumo["sucesso"] == 0 and resumo["parcial"] == processadas and orcamento_web <= 0:
        return SEM_COTA, "Sem cota de busca web: só a Receita Federal foi consultada (status parcial)."
    if resumo["parcial"] or resumo["falha"] or resumo.get("interrompida_por"):
        return PARCIAL, f"{resumo['sucesso']} sucesso, {resumo['parcial']} parcial, {resumo['falha']} falha."
    return CONCLUIDO, f"{processadas} empresa(s) enriquecida(s)."


def executar_rotina(conexao: sqlite3.Connection, *, perfil: dict, carregar_df: Callable[[], object],
                    providers_descoberta: list, providers_contato: list, meta_descoberta: int | None = None,
                    meta_enriquecimento: int = fila_enriquecimento.META_PADRAO, incluir_fora_da_regiao: bool = True,
                    pausa: float = 1.0, com_descoberta: bool = True, com_editais: bool = False, buscar_editais: Callable | None = None,
                    origem: str = "MANUAL", dormir: Callable[[float], None] | None = None) -> dict:
    """Roda as quatro etapas. Cada uma isolada: exceção vira FALHOU e a rotina segue."""
    descoberta_empresas.criar_tabelas(conexao)
    resumo: dict = {"etapas": {}}

    # 1) Descoberta ------------------------------------------------------------------
    if com_descoberta:
        registrar_etapa(conexao, "Descoberta", EXECUTANDO)
        try:
            r = descoberta_empresas.executar_descoberta(conexao, providers_descoberta, perfil, meta=meta_descoberta, origem=origem)
            t = r["totais"]
            detalhe = (f"{t['novas_total']} nova(s) de {r['meta']} (meta): {t['novas_confirmadas']} com CNPJ, {t['novas_candidatas']} candidata(s) "
                       f"sem CNPJ, {t['possiveis_duplicatas']} possível(is) duplicata(s); {t['existentes']} já existente(s) e "
                       f"{t['rejeitadas']} rejeitada(s) por dados insuficientes.")
            notas = [f"{n}: {i['detalhe']}" for n, i in r["providers"].items() if i["detalhe"] and i["status"] not in ("CONCLUIDO", "DISPONIVEL")]
            registrar_etapa(conexao, "Descoberta", r["status"], detalhe + (" " + " ".join(notas) if notas else ""), r)
            resumo["etapas"]["Descoberta"] = r["status"]
        except Exception as erro:
            registrar_etapa(conexao, "Descoberta", FALHOU, f"{type(erro).__name__}: {erro}")
            resumo["etapas"]["Descoberta"] = FALHOU
    else:
        registrar_etapa(conexao, "Descoberta", PENDENTE, "Desligada nesta execução (--sem-descoberta).")

    # 2) Enriquecimento + 3) Contatos --------------------------------------------------
    execucao = None
    registrar_etapa(conexao, "Enriquecimento", EXECUTANDO)
    try:
        kwargs = {"dormir": dormir} if dormir else {}
        execucao = fila_enriquecimento.executar(
            conexao, carregar_df(), providers_contato, meta=meta_enriquecimento, origem=origem,
            incluir_fora_da_regiao=incluir_fora_da_regiao, pausa_entre_empresas=pausa, **kwargs)
        status, detalhe = _status_enriquecimento(execucao, fila_enriquecimento.orcamento_serpapi(conexao))
        registrar_etapa(conexao, "Enriquecimento", status, detalhe, execucao)
        resumo["etapas"]["Enriquecimento"] = status
    except Exception as erro:
        registrar_etapa(conexao, "Enriquecimento", FALHOU, f"{type(erro).__name__}: {erro}")
        resumo["etapas"]["Enriquecimento"] = FALHOU

    if execucao is not None:
        novos = conexao.execute("SELECT COALESCE(SUM(contatos_novos), 0) FROM enriquecimento_itens WHERE execucao_id = ?",
                                (execucao["execucao_id"],)).fetchone()[0]
        status_contatos = CONCLUIDO if resumo["etapas"].get("Enriquecimento") != FALHOU else FALHOU
        registrar_etapa(conexao, "Contatos", status_contatos, f"{novos} contato(s) institucional(is) novo(s) nesta execução "
                        "(vêm da Receita Federal, da busca web e de e-mail/site já cadastrados — nenhum contato pessoal é inventado).",
                        {"contatos_novos": novos})
        resumo["etapas"]["Contatos"] = status_contatos
    else:
        registrar_etapa(conexao, "Contatos", FALHOU, "O enriquecimento falhou; nenhum contato foi coletado.")
        resumo["etapas"]["Contatos"] = FALHOU

    # 4) Editais -----------------------------------------------------------------------
    if com_editais and buscar_editais:
        registrar_etapa(conexao, "Editais", EXECUTANDO)
        try:
            r = buscar_editais()
            # relatório de busca_editais.executar_busca: sem campo "status"; a situação sai dos contadores/erros
            if r.get("orcamento_esgotado"):
                status_ed = SEM_COTA
            elif r.get("erros") and not (r.get("chamadas_api") or r.get("consultas_do_cache")):
                status_ed = FALHOU
            else:
                status_ed = PARCIAL if r.get("erros") else CONCLUIDO
            registrar_etapa(conexao, "Editais", status_ed,
                            f"{r.get('novos', 0)} edital(is) novo(s); {r.get('chamadas_api', 0)} chamada(s) à API e "
                            f"{r.get('consultas_do_cache', 0)} consulta(s) vinda(s) do cache." + (f" Avisos: {'; '.join(r['erros'][:2])}" if r.get("erros") else ""))
            resumo["etapas"]["Editais"] = status_ed
        except Exception as erro:
            registrar_etapa(conexao, "Editais", FALHOU, f"{type(erro).__name__}: {erro}")
            resumo["etapas"]["Editais"] = FALHOU
    else:
        registrar_etapa(conexao, "Editais", PENDENTE, "Não roda na rotina automática porque gasta cota de busca (SerpApi); "
                        "use o Radar de Editais ou --com-editais.")
    return resumo
