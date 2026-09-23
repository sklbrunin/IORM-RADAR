"""Interface da descoberta de empresas: Configurações → Descoberta de Empresas e Rotina diária → etapas."""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from processamento import banco, descoberta_empresas as D, rotina_etapas

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "iorm_radar.db"


@pytest.fixture(scope="module")
def banco_copia(tmp_path_factory):
    if not BANCO.exists():
        pytest.skip("banco real não disponível")
    destino = tmp_path_factory.mktemp("descob_ui") / "iorm_radar.db"
    shutil.copy(BANCO, destino)
    con = banco.conectar(destino)
    D.criar_tabelas(con)
    con.execute("INSERT INTO empresas (razao_social, cidade, estado, dominio, estagio_cadastro, origem_descoberta, criado_em, atualizado_em) "
                "VALUES ('Candidata de Teste UI', 'Salvador', 'BA', 'candidatateste.com.br', 'CANDIDATA', 'Apollo', 'x', 'x')")
    con.commit()
    rotina_etapas.registrar_etapa(con, "Descoberta", "PARCIAL", "3 nova(s) de 50 (meta)")
    con.close()
    return destino


def _app(modulo: str, banco_copia: Path):
    from streamlit.testing.v1 import AppTest

    corpo = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{RAIZ}")
        from pathlib import Path
        from paginas import _shared
        _shared.CAMINHO_DB = Path(r"{banco_copia}")
        _shared.garantir_tabelas_novas()
        _shared.injetar_css()
        from paginas import {modulo}
        {modulo}.render()
    """)
    app = AppTest.from_string(corpo, default_timeout=120).run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def test_configuracoes_mostra_os_provedores_de_descoberta_e_a_verdade_sobre_os_conectores(banco_copia):
    app = _app("configuracoes", banco_copia)
    texto = " ".join(m.value for m in app.markdown) + " ".join(c.value for c in app.caption)
    assert "Provedores de descoberta de empresas" in texto
    assert "não conseguem chamá-los" in texto and "APOLLO_API_KEY" in texto
    tabela = next(d for d in app.dataframe if "Como o app acessa" in d.value.columns)
    provedores = list(tabela.value["Provedor"])
    assert any("SALIC" in p for p in provedores) and any("Apollo" in p for p in provedores) and any("Lusha" in p for p in provedores)
    situacoes = dict(zip(provedores, tabela.value["Situação"]))
    assert all("Sem credencial" in s for p, s in situacoes.items() if any(n in p for n in ("Apollo", "Lusha", "Snov")))
    assert any("Candidata de Teste UI" in str(d.value) for d in app.dataframe)  # candidata aguardando validação


def test_configuracoes_valida_candidata_pela_interface_exigindo_cnpj_valido(banco_copia):
    app = _app("configuracoes", banco_copia)
    app.text_input(key="descob_cand_cnpj").set_value("11111111111111")
    app.button(key="descob_cand_confirmar").click().run()
    assert any("inválido" in e.value.lower() for e in app.error)


def test_rotina_diaria_mostra_as_quatro_etapas_com_status(banco_copia):
    app = _app("rotina_diaria", banco_copia)
    texto = " ".join(m.value for m in app.markdown)
    for etapa in ("Descoberta", "Enriquecimento", "Contatos", "Editais"):
        assert f"**{etapa}**" in texto
    assert "Parcial" in texto and "Pendente" in texto
    assert any(m.label == "Meta de empresas novas/dia" for m in app.metric)


def test_etapa_editais_interpreta_o_relatorio_da_busca(tmp_path):
    con = banco.conectar(tmp_path / "t.db")
    banco.criar_tabelas(con)
    banco.criar_tabelas_enriquecimento(con)
    common = dict(perfil={"cidades": [], "estados": [], "territorios": []}, carregar_df=lambda: __import__("pandas").DataFrame(),
                  providers_descoberta=[], providers_contato=[], com_descoberta=False, com_editais=True, dormir=lambda s: None)
    casos = [({"orcamento_esgotado": True, "erros": ["x"]}, "SEM_COTA"), ({"erros": ["falha"], "chamadas_api": 0}, "FALHOU"),
             ({"erros": ["aviso"], "chamadas_api": 2}, "PARCIAL"), ({"erros": [], "chamadas_api": 1, "novos": 2}, "CONCLUIDO")]
    for relatorio, esperado in casos:
        rotina_etapas.executar_rotina(con, buscar_editais=lambda r=relatorio: r, **common)
        assert {e["etapa"]: e["status"] for e in rotina_etapas.etapas_do_dia(con)}["Editais"] == esperado
