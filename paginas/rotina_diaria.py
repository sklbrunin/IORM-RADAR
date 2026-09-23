"""Rotina diária de enriquecimento — painel administrativo.

Mostra o que a rotina (coleta/enriquecimento_diario.py) fez, o que vem
a seguir e se ela está de fato agendada no Windows. Nada aqui é
simulado: tudo vem das tabelas enriquecimento_* e do Agendador de Tarefas."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from processamento import descoberta_empresas, rotina_etapas
from processamento import fila_enriquecimento as fila
from paginas import _shared

NOME_TAREFA = "IORM Radar - Enriquecimento diário"
SCRIPT = _shared.RAIZ_PROJETO / "coleta" / "enriquecimento_diario.py"
_ROTULO_STATUS = {"SUCESSO": "✅ Sucesso", "PARCIAL": "🟡 Parcial", "FALHA": "🔴 Falha"}


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "Nunca executada"
    return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y às %H:%M")


def _status_agendamento() -> dict:
    """Consulta o Agendador de Tarefas do Windows (independente do idioma do
    sistema). Fora do Windows, ou sem a tarefa, devolve instalado=False."""
    if sys.platform != "win32":
        return {"instalado": False, "motivo": "Agendador do Windows não disponível neste sistema."}
    comando = (
        f"$t = Get-ScheduledTask -TaskName '{NOME_TAREFA}' -ErrorAction SilentlyContinue; "
        "if (-not $t) { '{}' ; exit } "
        f"$i = Get-ScheduledTaskInfo -TaskName '{NOME_TAREFA}'; "
        "[pscustomobject]@{ estado = [string]$t.State; proxima = $i.NextRunTime.ToString('o'); "
        "ultima = $i.LastRunTime.ToString('o'); resultado = $i.LastTaskResult } | ConvertTo-Json -Compress"
    )
    try:
        saida = subprocess.run(["powershell", "-NoProfile", "-Command", comando], capture_output=True, text=True, timeout=20)
        dados = json.loads(saida.stdout.strip() or "{}")
    except Exception:
        return {"instalado": False, "motivo": "Não foi possível consultar o Agendador de Tarefas."}
    if not dados:
        return {"instalado": False, "motivo": "A tarefa ainda não foi instalada."}
    return {"instalado": True, **dados}


def _executar_agora() -> None:
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([sys.executable, str(SCRIPT)], cwd=str(_shared.RAIZ_PROJETO), creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def render() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    conexao = _shared.conectar()
    fila.criar_tabelas(conexao)
    resumo = fila.resumo_admin(conexao, dados["df_mesclado"])
    ultima = resumo["ultima_execucao"]
    agenda = _status_agendamento()

    descoberta_empresas.criar_tabelas(conexao)
    _shared.cabecalho("Rotina diária", "Descoberta de empresas novas, enriquecimento e contatos — cada etapa dentro dos limites de cada API.")

    # ------------------------------------------------ agendamento (a verdade sobre estar automatizada ou não)
    if agenda["instalado"]:
        st.markdown(
            f"<div class='iorm-info'>✅ <b>Agendada no Windows</b> (tarefa “{NOME_TAREFA}”, estado: {agenda['estado']}). "
            f"Resultado da última execução do agendador: {agenda['resultado']} (0 = sucesso).</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div class='iorm-limitacao'><b>Ainda não está agendada.</b> {agenda['motivo']} Enquanto a tarefa não for "
            "instalada, a rotina só roda quando alguém a inicia (botão abaixo ou linha de comando). "
            "Passo a passo para instalar está no fim desta página.</div>", unsafe_allow_html=True)

    # ------------------------------------------------ etapas de hoje (v9)
    _shared.secao("Etapas de hoje", "🧭",
                  "Descoberta (achar empresas novas) e Enriquecimento (completar as que já existem) são etapas separadas, cada uma com seu status.")
    etapas = rotina_etapas.etapas_do_dia(conexao)
    for coluna, etapa in zip(st.columns(4), etapas):
        with coluna:
            with st.container(border=True):
                st.markdown(f"**{etapa['etapa']}**")
                st.markdown(rotina_etapas.ROTULOS_STATUS[etapa["status"]])
                st.caption(etapa["detalhe"] or "Ainda não executada hoje.")
    resumo_desc = descoberta_empresas.situacao_providers(conexao)
    novas_hoje = conexao.execute(
        "SELECT COUNT(*) FROM empresas_origens WHERE resultado != 'EXISTENTE' AND substr(descoberto_em, 1, 10) = ?",
        (datetime.now(timezone.utc).strftime("%Y-%m-%d"),)).fetchone()[0]
    d1, d2, d3 = st.columns(3)
    d1.metric("Meta de empresas novas/dia", descoberta_empresas.empresas_novas_por_dia(), help="Variável `EMPRESAS_NOVAS_POR_DIA` (padrão 50).")
    d2.metric("Descobertas hoje", novas_hoje)
    d3.metric("Candidatas sem CNPJ", descoberta_empresas.contar_candidatas(conexao),
              help="Achadas por provedores sem CNPJ; ficam fora dos prospects até a equipe validar (Configurações → Descoberta de Empresas).")
    st.dataframe(
        pd.DataFrame([{"Provedor": l["rotulo"], "Situação": "✅ Disponível" if l["estado"] == "DISPONIVEL" else
                       {"SEM_CREDENCIAL": "🔑 Sem credencial", "SEM_COTA": "🟠 Sem cota"}.get(l["estado"], l["estado"]),
                       "Ligado": "Sim" if l["habilitado"] else "Não", "Créditos no mês": l["creditos_no_mes"]} for l in resumo_desc]),
        hide_index=True, use_container_width=True)

    # ------------------------------------------------ indicadores
    _shared.secao("Situação", "📊")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Última execução", _fmt_dt(ultima["finalizado_em"] or ultima["iniciado_em"]) if ultima else "Nunca executada")
    if agenda["instalado"] and agenda.get("proxima"):
        c2.metric("Próxima execução", _fmt_dt(agenda["proxima"]))
    else:
        c2.metric("Próxima execução", "Sem agendamento")
    c3.metric("Processadas hoje", f"{resumo['hoje']['processadas']} / {resumo['meta_dia']}")
    c4.metric("Total acumulado", resumo["total_acumulado"], help="Empresas distintas já processadas pela rotina.")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Sucesso hoje", resumo["hoje"]["sucesso"])
    c6.metric("Parcial hoje", resumo["hoje"]["parcial"], help="Algum provedor foi pulado (ex: cota de busca web) ou falhou; nova tentativa em 3 dias.")
    c7.metric("Falha hoje", resumo["hoje"]["falha"], help="Nada funcionou; nova tentativa em 1 dia (máximo 3 tentativas).")
    c8.metric("Elegíveis na fila", f"{resumo['elegiveis_novas']:,}".replace(",", "."),
              help=f"Prospects com CNPJ, nunca pesquisados. Mais {resumo['elegiveis_retentativa']} aguardando nova tentativa.")

    if ultima and ultima["observacao"]:
        st.markdown(f"<div class='iorm-aviso'><b>Última execução:</b> {ultima['observacao']}</div>", unsafe_allow_html=True)

    # ------------------------------------------------ cota de API
    _shared.secao("Limites de API (nunca ultrapassados)", "🚦",
                  "A rotina só usa a busca web enquanto houver cota; a Receita Federal (BrasilAPI) é gratuita e é sempre consultada.")
    s = resumo["serpapi"]
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("SerpApi — usadas no mês", f"{s['usadas_no_mes']} / {s['limite_mensal']}")
    a2.metric("Reserva p/ pesquisa manual", s["reserva_manual"])
    a3.metric("Cota que a rotina ainda pode usar", s["orcamento_da_rotina"],
              help=f"Cada empresa gasta {fila.CONSULTAS_WEB_POR_EMPRESA} consultas de busca web.")
    a4.metric("BrasilAPI — consultas no mês", resumo["brasilapi_usadas_no_mes"])
    empresas_web = s["orcamento_da_rotina"] // fila.CONSULTAS_WEB_POR_EMPRESA
    st.caption(
        f"Com a cota atual, a busca web alcança cerca de {empresas_web} empresa(s) até o fim do mês. As demais são "
        "enriquecidas só pela Receita Federal (status “Parcial”) e completadas quando houver cota. Para sustentar 30 empresas/dia "
        "com busca web é preciso um plano pago da SerpApi (ajuste `SERPAPI_LIMITE_MENSAL` no .env)."
    )

    # ------------------------------------------------ executar agora
    _shared.secao("Executar agora", "▶")
    if st.button("▶ Executar a rotina agora (até a meta do dia)", key="rotina_agora"):
        _executar_agora()
        st.success("Rotina iniciada em segundo plano. Atualize esta página em alguns minutos para ver o resultado.")
    if st.button("🔄 Atualizar painel", key="rotina_atualizar"):
        _shared.limpar_cache()
        st.rerun()

    # ------------------------------------------------ próximas da fila / hoje / histórico
    _shared.secao("Próximas da fila", "📋", "As 10 próximas empresas: primeiro as nunca pesquisadas, por Região IORM e prioridade.")
    if resumo["proximas_da_fila"]:
        st.dataframe(
            pd.DataFrame(resumo["proximas_da_fila"]).rename(columns={
                "razao_social": "Empresa", "cidade": "Cidade", "tipo_fila": "Tipo", "regiao_iorm": "Região IORM"})[
                ["Empresa", "Cidade", "Região IORM", "Tipo"]],
            use_container_width=True, hide_index=True,
            column_config={"Empresa": st.column_config.TextColumn(width=430), "Cidade": st.column_config.TextColumn(width=180),
                           "Região IORM": st.column_config.TextColumn(width=200), "Tipo": st.column_config.TextColumn(width=140)},
        )
    else:
        _shared.estado_vazio("Nenhuma empresa elegível na fila agora.", "📋")

    _shared.secao("Processadas hoje", "🗓️")
    itens = fila.itens_de_hoje(conexao)
    if itens:
        tabela = pd.DataFrame(itens)
        tabela["status"] = tabela["status"].map(lambda x: _ROTULO_STATUS.get(x, x))
        st.dataframe(
            tabela.rename(columns={"razao_social": "Empresa", "cidade": "Cidade", "status": "Resultado", "detalhe": "Detalhe",
                                   "contatos_novos": "Contatos novos", "tipo_fila": "Fila"})[
                ["Empresa", "Cidade", "Resultado", "Fila", "Contatos novos", "Detalhe"]],
            use_container_width=True, hide_index=True,
            column_config={"Empresa": st.column_config.TextColumn(width=380), "Detalhe": st.column_config.TextColumn(width=520),
                           "Resultado": st.column_config.TextColumn(width=130)},
        )
    else:
        _shared.estado_vazio("Nenhuma empresa processada hoje ainda.", "🗓️")

    _shared.secao("Histórico de execuções", "🕒")
    historico = conexao.execute("SELECT * FROM enriquecimento_execucoes ORDER BY id DESC LIMIT 15").fetchall()
    if historico:
        tabela = pd.DataFrame([dict(l) for l in historico])
        tabela["iniciado_em"] = tabela["iniciado_em"].map(_fmt_dt)
        st.dataframe(
            tabela.rename(columns={"iniciado_em": "Início", "origem": "Origem", "meta": "Meta", "processadas": "Processadas",
                                   "sucesso": "Sucesso", "parcial": "Parcial", "falha": "Falha", "dentro_da_regiao": "Na região",
                                   "fora_da_regiao": "Fora da região", "chamadas_serpapi": "SerpApi", "observacao": "Observação"})[
                ["Início", "Origem", "Meta", "Processadas", "Sucesso", "Parcial", "Falha", "Na região", "Fora da região", "SerpApi", "Observação"]],
            use_container_width=True, hide_index=True,
            column_config={"Início": st.column_config.TextColumn(width=180), "Observação": st.column_config.TextColumn(width=520)},
        )
    else:
        _shared.estado_vazio("Nenhuma execução registrada ainda.", "🕒")

    with st.expander("Como agendar no Windows e como conferir que está funcionando"):
        st.markdown(
            "**Instalar (uma vez)** — PowerShell na pasta do projeto:\n"
            "```\npowershell -ExecutionPolicy Bypass -File coleta\\agendar_enriquecimento_windows.ps1\n```\n"
            "Horário diferente: `... -Horario 06:00`. Roda com o seu usuário, sem administrador; se o computador estiver "
            "desligado no horário, roda assim que ligar.\n\n"
            "**Conferir:** `... -Status` mostra estado, última e próxima execução — e esta página passa a mostrar "
            "“Agendada no Windows”. **Testar já:** `Start-ScheduledTask -TaskName 'IORM Radar - Enriquecimento diário'`. "
            "**Remover:** `... -Remover`.\n\n"
            "**Log de cada execução:** `dados\\logs\\enriquecimento_diario.log` (uma linha JSON por execução) e "
            "`dados\\logs\\agendado.out.log` (saída do agendador)."
        )
    conexao.close()
