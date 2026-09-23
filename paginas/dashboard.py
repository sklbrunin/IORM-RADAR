"""Dashboard: a primeira tela do captador. Responde, em poucos segundos, quatro perguntas:
  1. Como está a base? (quantas empresas, quantas são prospects, quantas já têm relacionamento)
  2. Que oportunidades abertas valem meu tempo agora? (editais com alta aderência — clicáveis)
  3. O que preciso fazer hoje? (prioridades, follow-ups)
  4. Onde estou no funil?"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from processamento import crm, editais, metricas, osc
from paginas import _shared

LIMIAR_PRIORITARIA = 70
LIMIAR_ADERENCIA_ALTA = 7.0
CRITERIOS_MINIMOS = 3  # de 6: nota calculada com menos que isso não entra em "alta aderência"
MAX_CARTOES_EDITAL = 6


def _abrir_edital(edital_id: int) -> None:
    """Callback dos cartões: guarda o edital em foco e leva à página de Editais."""
    st.session_state["edital_em_foco"] = edital_id
    _shared.ir_para_pagina("radar_editais")


def _lista_curta(texto: str | None, maximo: int = 5) -> str | None:
    """Lista separada por vírgulas encurtada de forma EXPLÍCITA ("e mais 10 na ficha") — o texto completo fica na ficha."""
    if not texto:
        return texto
    itens = [i.strip() for i in texto.split(",") if i.strip()]
    if len(itens) <= maximo:
        return texto
    return ", ".join(itens[:maximo]) + f" e mais {len(itens) - maximo} (lista completa na ficha)"


def _cartao_edital(edital: dict) -> None:
    with st.container(border=True):
        if st.button(edital["titulo"], key=f"dash_edital_titulo_{edital['id']}", type="tertiary",
                     use_container_width=True, help="Abrir a ficha completa deste edital"):
            _abrir_edital(edital["id"])
        st.markdown(
            f"<span class='iorm-badge iorm-badge-verde'>Aderência {_shared.formatar_nota(edital['nota_final'])}</span> "
            "<span class='iorm-badge iorm-badge-verde'>🟢 ABERTO</span>",
            unsafe_allow_html=True,
        )
        nd = "Não identificado na fonte"
        valor = edital.get("valor_texto") or (_shared.formatar_moeda(edital["valor_numerico"]) if edital.get("valor_numerico") else nd)
        linhas = [
            ("Instituição", edital.get("organizacao_promotora") or nd),
            ("Prazo", _shared.formatar_data(edital.get("data_encerramento"))),
            ("Área temática", _lista_curta(edital.get("area_tematica")) or nd),
            ("Valor", valor),
            ("Localização", edital.get("territorio") or nd),
        ]
        st.markdown(
            "".join(f"<div class='iorm-edital-linha'><b>{rotulo}:</b> {texto}</div>" for rotulo, texto in linhas),
            unsafe_allow_html=True,
        )
        resumo = _shared.resumir_texto(edital.get("texto_resumo") or edital.get("descricao"), 240)
        if resumo:
            st.markdown(f"<div class='iorm-edital-resumo'>{resumo}</div>", unsafe_allow_html=True)
        if st.button("Abrir ficha completa →", key=f"dash_edital_abrir_{edital['id']}", use_container_width=True):
            _abrir_edital(edital["id"])


def render() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    df_mesclado = dados["df_mesclado"]

    conexao = _shared.conectar()
    perfil_osc_row = osc.obter_osc_principal(conexao)
    perfil_osc = osc.carregar_perfil_completo(conexao, perfil_osc_row["id"]) if perfil_osc_row else None

    oportunidades_crm = [dict(o) for o in crm.listar_oportunidades(conexao)]
    todos_editais = editais.listar_editais(conexao)
    grupos_editais = editais.agrupar_por_situacao(todos_editais)
    conexao.close()

    empresas_ja_no_crm = {op["empresa_id"] for op in oportunidades_crm if op.get("empresa_id")}

    # Editais ABERTOS com aderência calculada contra o perfil atual da OSC (mesmo motor da página de Editais).
    abertos_com_nota = editais.abertos_com_aderencia(todos_editais, perfil_osc) if perfil_osc else []
    editais_alta_aderencia = [
        e for e in abertos_com_nota
        if e["nota_final"] is not None and e["nota_final"] >= LIMIAR_ADERENCIA_ALTA
        and e["aderencia"]["criterios_avaliados"] >= CRITERIOS_MINIMOS
    ]

    # Só prospects entram em listas de prioridade — Linha Cruzada tem relacionamento, não é abordagem nova.
    df_prospects = df_mesclado[df_mesclado["eh_prospect"]] if not df_mesclado.empty else df_mesclado
    empresas_prioritarias_df = (
        df_prospects[df_prospects["prioridade_prospeccao"] >= LIMIAR_PRIORITARIA] if not df_prospects.empty else df_prospects
    )
    empresas_prioritarias_fora_crm = (
        empresas_prioritarias_df[~empresas_prioritarias_df["id"].isin(empresas_ja_no_crm)]
        if not empresas_prioritarias_df.empty else empresas_prioritarias_df
    )

    valor_potencial = crm.valor_potencial_total(oportunidades_crm)
    follow_ups = crm.classificar_follow_ups(oportunidades_crm, hoje=editais.hoje_brasil())
    sem_proxima_acao = crm.oportunidades_sem_proxima_acao(oportunidades_crm)
    contagem_estagios = crm.contar_por_estagio(oportunidades_crm)
    contadores = metricas.contadores_empresas(df_mesclado)

    nome_osc = perfil_osc_row["nome_fantasia"] or perfil_osc_row["nome"] if perfil_osc_row else "sua OSC"
    _shared.cabecalho("Dashboard", f"Visão da captação de recursos do {nome_osc} — o que olhar agora.")

    # ============================================================ 1. COMO ESTÁ A BASE
    _shared.secao("Base de empresas", "🏢", "Cada número tem um significado só — prospects e Linha Cruzada nunca se misturam.")
    b1, b2, b3, b4, b5 = st.columns(5)
    b1.metric("Empresas na base", _shared.formatar_numero(contadores["total"]), help="Todos os registros. Nada é apagado.")
    b2.metric("Prospects", _shared.formatar_numero(contadores["prospects"]),
              help="Elegíveis para prospecção: empresas sem relacionamento comprovado com o IORM.")
    b3.metric("Linha Cruzada", _shared.formatar_numero(contadores["linha_cruzada"]),
              help="Empresas com relacionamento comprovado com o IORM — ficam fora da prospecção nova.")
    b4.metric("Prospects pesquisados", _shared.formatar_numero(contadores["pesquisadas"]),
              help="Prospects que já passaram por enriquecimento (contatos, presença digital, evidências).")
    b5.metric("Prospects não pesquisados", _shared.formatar_numero(contadores["nao_pesquisadas"]),
              help="Prospects ainda sem enriquecimento. A rotina diária trabalha nessa fila.")
    if contadores["reabertas"]:
        st.caption(f"{contadores['reabertas']} empresa(s) da Linha Cruzada estão com a prospecção reaberta (justificativa registrada) e "
                   "por isso contam também como prospects.")

    # ============================================================ 2. OPORTUNIDADES ABERTAS
    _shared.secao(
        "Editais com alta aderência", "🏆",
        f"Somente editais ABERTOS (prazo real ainda vigente) com aderência ≥ {_shared.formatar_nota(LIMIAR_ADERENCIA_ALTA).replace('/10', '')}, "
        f"calculada com pelo menos {CRITERIOS_MINIMOS} dos 6 critérios. Clique no título para abrir a ficha completa.",
    )
    if not perfil_osc:
        _shared.estado_vazio("Cadastre o Cérebro da OSC para calcular aderência.", "🧠")
    elif not editais_alta_aderencia:
        n_nc = len(grupos_editais["nao_confirmados"])
        _shared.estado_vazio(
            f"Nenhum edital aberto com aderência alta agora. Editais abertos: {len(abertos_com_nota)}. "
            f"Aguardando confirmação de prazo: {n_nc}.", "📋",
        )
        if st.button("Ver Radar de Editais →", key="dash_ir_editais"):
            _shared.ir_para_pagina("radar_editais")
    else:
        total_alta = len(editais_alta_aderencia)
        ver_todos = bool(st.session_state.get("dash_editais_ver_todos"))
        mostrados = editais_alta_aderencia if ver_todos else editais_alta_aderencia[:MAX_CARTOES_EDITAL]
        st.caption(f"{total_alta} edital(is) aberto(s) com alta aderência" + (f" — mostrando {len(mostrados)} de {total_alta}." if len(mostrados) < total_alta else "."))
        for inicio in range(0, len(mostrados), 3):
            colunas = st.columns(3)
            for coluna, edital in zip(colunas, mostrados[inicio:inicio + 3]):
                with coluna:
                    _cartao_edital(edital)
        if total_alta > MAX_CARTOES_EDITAL:
            rotulo = "Mostrar menos" if ver_todos else f"Ver todos os {total_alta} editais"
            if st.button(rotulo, key="dash_editais_alternar_lista"):
                st.session_state["dash_editais_ver_todos"] = not ver_todos
                st.rerun()

    # ============================================================ 3. CAPTAÇÃO E AÇÃO
    _shared.secao("Captação", "📊")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Editais abertos", len(abertos_com_nota), help="Aberto = prazo real futuro + link da fonte. Não confirmados ficam de fora.")
    c2.metric("Oportunidades em andamento", sum(1 for o in oportunidades_crm if not o["estagio"].startswith("Fechado")))
    c3.metric("Follow-ups pendentes", len(follow_ups["atrasadas"]) + len(follow_ups["hoje"]))
    c4.metric("Valor potencial em negociação", _shared.formatar_moeda(valor_potencial))
    c5.metric("Contatos encontrados", _shared.formatar_numero(len(dados["df_contatos_export"])))

    _shared.secao("Prioridades de hoje", "🔥", "O que merece atenção do captador agora — gerado automaticamente.")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"**Prospects prioritários ainda fora do Pipeline** (prioridade ≥{LIMIAR_PRIORITARIA}: {len(empresas_prioritarias_fora_crm)})")
        if empresas_prioritarias_fora_crm.empty:
            _shared.estado_vazio("Nenhum prospect prioritário pendente de ação.", "✅")
        else:
            top5 = empresas_prioritarias_fora_crm.sort_values("prioridade_prospeccao", ascending=False).head(5)
            for linha in top5.itertuples():
                st.markdown(
                    f"<div class='iorm-kanban-cartao'><b>{linha.razao_social}</b> — {linha.cidade or 'cidade não disponível'}"
                    f"<br>Prioridade: {linha.prioridade_prospeccao}/100</div>",
                    unsafe_allow_html=True,
                )
    with col_b:
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

    # ============================================================ 4. FUNIL
    _shared.secao("Funil de Captação", "🔀", "Pipeline atual por estágio.")
    if not oportunidades_crm:
        _shared.estado_vazio("Nenhuma oportunidade no Pipeline ainda. Crie uma em Captação → Pipeline.", "🤝")
    else:
        _shared.grafico_barras(pd.Series(dict(contagem_estagios)), "Oportunidades")

    # ============================================================ RADAR DE PROSPECTS
    _shared.secao("Melhores prospects", "🎯", "As 5 empresas prospect com maior prioridade de prospecção (Linha Cruzada não entra aqui).")
    if df_prospects.empty:
        _shared.estado_vazio("Nenhuma empresa no radar.")
    else:
        top_empresas = df_prospects.sort_values("prioridade_prospeccao", ascending=False).head(5)
        st.dataframe(
            top_empresas[["razao_social", "cidade", "prioridade_prospeccao"]].rename(
                columns={"razao_social": "Empresa", "cidade": "Cidade", "prioridade_prospeccao": "Prioridade"}
            ),
            use_container_width=True, hide_index=True,
            column_config={"Empresa": st.column_config.TextColumn(width=520), "Cidade": st.column_config.TextColumn(width=200),
                           "Prioridade": st.column_config.NumberColumn(width=120)},
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
