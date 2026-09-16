"""Dashboard: a primeira tela do captador. Precisa responder em poucos
segundos "o que está acontecendo e o que eu deveria olhar agora?" —
não é só uma lista de números, é contexto priorizado."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from processamento import crm, editais, osc
from paginas import _shared

LIMIAR_PRIORITARIA = 70
LIMIAR_ADERENCIA_ALTA = 7.0


def render() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    estatisticas = dados["estatisticas"]
    df_mesclado = dados["df_mesclado"]

    conexao = _shared.conectar()
    perfil_osc_row = osc.obter_osc_principal(conexao)
    perfil_osc = osc.carregar_perfil_completo(conexao, perfil_osc_row["id"]) if perfil_osc_row else None

    oportunidades_crm = [dict(o) for o in crm.listar_oportunidades(conexao)]
    lista_editais = [dict(e) for e in editais.listar_editais(conexao)]

    empresas_ja_no_crm = {op["empresa_id"] for op in oportunidades_crm if op.get("empresa_id")}

    # aderência de cada edital contra o perfil atual da OSC (mesmo motor do Radar de Editais)
    editais_com_nota = []
    if perfil_osc:
        for edital in lista_editais:
            resultado = editais.calcular_aderencia(edital, perfil_osc)
            editais_com_nota.append({**edital, "nota_final": resultado["nota_final"]})
    conexao.close()

    empresas_prioritarias_df = (
        df_mesclado[df_mesclado["prioridade_prospeccao"] >= LIMIAR_PRIORITARIA] if not df_mesclado.empty else df_mesclado
    )
    empresas_prioritarias_fora_crm = (
        empresas_prioritarias_df[~empresas_prioritarias_df["id"].isin(empresas_ja_no_crm)]
        if not empresas_prioritarias_df.empty else empresas_prioritarias_df
    )

    editais_alta_aderencia = [e for e in editais_com_nota if e["nota_final"] and e["nota_final"] >= LIMIAR_ADERENCIA_ALTA]
    valor_potencial = crm.valor_potencial_total(oportunidades_crm)
    follow_ups = crm.classificar_follow_ups(oportunidades_crm, hoje=date.today())
    sem_proxima_acao = crm.oportunidades_sem_proxima_acao(oportunidades_crm)
    contagem_estagios = crm.contar_por_estagio(oportunidades_crm)

    nome_osc = perfil_osc_row["nome_fantasia"] or perfil_osc_row["nome"] if perfil_osc_row else "sua OSC"
    _shared.cabecalho("Dashboard", f"Visão da captação de recursos do {nome_osc} — o que olhar agora.")

    # ============================================================ VISÃO DA CAPTAÇÃO
    _shared.secao("Visão da Captação", "📊")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Empresas no radar", _shared.formatar_numero(estatisticas["empresas_mapeadas"]))
    c2.metric(f"Empresas prioritárias (score ≥{LIMIAR_PRIORITARIA})", len(empresas_prioritarias_df))
    c3.metric("Contatos encontrados", len(dados["df_contatos_export"]))
    c4.metric("Editais abertos", len(lista_editais))
    c5, c6, c7 = st.columns(3)
    c5.metric("Oportunidades em andamento", sum(1 for o in oportunidades_crm if not o["estagio"].startswith("Fechado")))
    c6.metric("Follow-ups pendentes", len(follow_ups["atrasadas"]) + len(follow_ups["hoje"]))
    c7.metric("Valor potencial em negociação", _shared.formatar_moeda(valor_potencial))

    # ============================================================ PRIORIDADES DE HOJE
    _shared.secao("Prioridades de hoje", "🔥", "O que merece atenção do captador agora — gerado automaticamente.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Empresas prioritárias ainda fora do Pipeline**")
        if empresas_prioritarias_fora_crm.empty:
            _shared.estado_vazio("Nenhuma empresa prioritária pendente de ação.", "✅")
        else:
            top5 = empresas_prioritarias_fora_crm.sort_values("prioridade_prospeccao", ascending=False).head(5)
            for linha in top5.itertuples():
                st.markdown(
                    f"<div class='iorm-kanban-cartao'><b>{linha.razao_social}</b> — {linha.cidade or 'cidade não disponível'}"
                    f"<br>Prioridade: {linha.prioridade_prospeccao}/100</div>",
                    unsafe_allow_html=True,
                )

        st.markdown("**Follow-ups vencidos**")
        if not follow_ups["atrasadas"]:
            _shared.estado_vazio("Nenhum follow-up atrasado.", "✅")
        else:
            for op in follow_ups["atrasadas"][:5]:
                st.markdown(
                    f"<div class='iorm-kanban-cartao' style='border-left-color:#C0392B'>"
                    f"<b>{op['titulo']}</b> — {op.get('empresa_nome') or 'sem empresa'}"
                    f"<br>Era para {_shared.formatar_data(op['proxima_acao_data'])}</div>",
                    unsafe_allow_html=True,
                )

    with col_b:
        st.markdown("**Editais com alta aderência**")
        if not perfil_osc:
            _shared.estado_vazio("Cadastre o Cérebro da OSC para calcular aderência.", "🧠")
        elif not editais_alta_aderencia:
            _shared.estado_vazio("Nenhum edital cadastrado com aderência ≥ 7,0 ainda.", "📋")
        else:
            for edital in sorted(editais_alta_aderencia, key=lambda e: e["nota_final"], reverse=True)[:5]:
                st.markdown(
                    f"<div class='iorm-kanban-cartao' style='border-left-color:#6FA82E'>"
                    f"<b>{edital['titulo']}</b><br>Aderência: {edital['nota_final']:.1f}/10</div>",
                    unsafe_allow_html=True,
                )

        st.markdown("**Oportunidades sem próxima ação**")
        if not sem_proxima_acao:
            _shared.estado_vazio("Todas as oportunidades abertas têm próxima ação definida.", "✅")
        else:
            for op in sem_proxima_acao[:5]:
                st.markdown(
                    f"<div class='iorm-kanban-cartao' style='border-left-color:#F0900F'>"
                    f"<b>{op['titulo']}</b> — {op.get('empresa_nome') or 'sem empresa'}<br>Estágio: {op['estagio']}</div>",
                    unsafe_allow_html=True,
                )

    # ============================================================ FUNIL DE CAPTAÇÃO
    _shared.secao("Funil de Captação", "🔀", "Pipeline atual por estágio.")
    if not oportunidades_crm:
        _shared.estado_vazio("Nenhuma oportunidade no Pipeline ainda. Crie uma em Captação → Pipeline.", "🤝")
    else:
        df_funil = pd.DataFrame(
            [{"Estágio": estagio, "Oportunidades": qtd} for estagio, qtd in contagem_estagios.items()]
        ).set_index("Estágio")
        st.bar_chart(df_funil)

    # ============================================================ RADAR DE OPORTUNIDADES
    _shared.secao("Radar de Oportunidades", "🎯", "As empresas e os editais mais relevantes agora.")
    col_c, col_d = st.columns(2)
    with col_c:
        st.markdown("**Top 5 empresas (Prioridade de Prospecção)**")
        if df_mesclado.empty:
            _shared.estado_vazio("Nenhuma empresa no radar.")
        else:
            top_empresas = df_mesclado.sort_values("prioridade_prospeccao", ascending=False).head(5)
            st.dataframe(
                top_empresas[["razao_social", "cidade", "prioridade_prospeccao"]].rename(
                    columns={"razao_social": "Empresa", "cidade": "Cidade", "prioridade_prospeccao": "Prioridade"}
                ),
                use_container_width=True, hide_index=True,
            )
    with col_d:
        st.markdown("**Top 5 editais (Aderência)**")
        if not editais_com_nota:
            _shared.estado_vazio("Nenhum edital cadastrado ainda.")
        else:
            top_editais = sorted([e for e in editais_com_nota if e["nota_final"]], key=lambda e: e["nota_final"], reverse=True)[:5]
            if not top_editais:
                _shared.estado_vazio("Nenhum edital com aderência calculável ainda.")
            else:
                st.dataframe(
                    pd.DataFrame([{"Edital": e["titulo"], "Aderência": f"{e['nota_final']:.1f}/10"} for e in top_editais]),
                    use_container_width=True, hide_index=True,
                )

    # ============================================================ ATIVIDADE RECENTE
    _shared.secao("Atividade recente", "🕒")
    conexao = _shared.conectar()
    pesquisas_recentes = conexao.execute(
        """SELECT h.executado_em, h.status, e.razao_social
           FROM historico_pesquisa h JOIN empresas e ON e.id = h.empresa_id
           ORDER BY h.executado_em DESC LIMIT 5"""
    ).fetchall()
    interacoes_recentes = crm.listar_interacoes_recentes(conexao, limite=5)
    conexao.close()

    col_e, col_f = st.columns(2)
    with col_e:
        st.markdown("**Últimas pesquisas de enriquecimento**")
        if not pesquisas_recentes:
            _shared.estado_vazio("Nenhuma pesquisa realizada ainda.")
        else:
            for p in pesquisas_recentes:
                st.markdown(
                    f"<div class='iorm-timeline-item'><span class='iorm-timeline-data'>{_shared.formatar_data(p['executado_em'])}</span>"
                    f"<span class='iorm-timeline-texto'>{p['razao_social']} — {p['status']}</span></div>",
                    unsafe_allow_html=True,
                )
    with col_f:
        st.markdown("**Últimas interações do Pipeline**")
        if not interacoes_recentes:
            _shared.estado_vazio("Nenhuma interação registrada ainda.")
        else:
            for i in interacoes_recentes:
                st.markdown(
                    f"<div class='iorm-timeline-item'><span class='iorm-timeline-data'>{_shared.formatar_data(i['data'])}</span>"
                    f"<span class='iorm-timeline-texto'>{i['tipo']} — {i['oportunidade_titulo']}: {i['descricao'] or 'sem descrição'}</span></div>",
                    unsafe_allow_html=True,
                )
