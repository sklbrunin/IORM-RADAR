from __future__ import annotations

import sqlite3

import pytest

from processamento import banco, incentivos_providers as ip


def _bruto(nome, cnpj, uf="SP", total=1000.0, municipio="Guaíra"):
    return {"nome": nome, "cgccpf": cnpj, "UF": uf, "municipio": municipio, "total_doado": total,
            "_links": {"self": f"https://api.salic.cultura.gov.br/api/v1/incentivadores/{cnpj or nome}"}}


def _paginador(paginas):
    """Simula a API: `paginas` é uma lista de listas de registros; total = soma."""
    total = sum(len(p) for p in paginas)

    def buscar(uf, offset):
        indice = offset // 100
        registros = paginas[indice] if indice < len(paginas) else []
        return {"total": total, "_embedded": {"incentivadores": registros}}

    return buscar


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    yield conn
    conn.close()


def _provider(paginas):
    return ip.SalicRouanetProvider(paginador=_paginador(paginas), pausa=0)


PAGINAS = [[_bruto("EMPRESA UM LTDA", "11444777000161"), _bruto("EMPRESA DOIS SA", "11222333000181", total=250.5)]]


def test_provider_normaliza_com_mecanismo_fonte_e_evidencia():
    registros = list(_provider(PAGINAS).coletar("SP"))
    assert len(registros) == 2
    inc = registros[0].incentivo
    assert inc["mecanismo"] == ip.MECANISMO_ROUANET
    assert inc["fonte"].startswith("SALIC") and inc["url_fonte"].startswith("https://api.salic.cultura.gov.br/")
    assert inc["uf"] == "SP" and inc["cidade"] == "Guaíra" and inc["valor"] == 1000.0
    assert registros[0].empresa["cnpj"] == "11444777000161" and registros[0].empresa["razao_social"] == "EMPRESA UM LTDA"


def test_registro_sem_nome_ou_url_e_descartado_nunca_completado():
    ruim = {"nome": "", "cgccpf": "11444777000161", "_links": {"self": "https://x/1"}}
    sem_url = {"nome": "SEM URL", "cgccpf": "11222333000181", "_links": {}}
    assert list(_provider([[ruim, sem_url]]).coletar("SP")) == []


def test_ingerir_grava_empresa_incentivo_e_mecanismo(conexao):
    resumo = ip.ingerir(conexao, _provider(PAGINAS), "SP")
    assert resumo == {"mecanismo": "LEI_ROUANET", "lidos": 2, "empresas_novas": 2, "empresas_existentes": 0,
                      "incentivos_novos": 2, "incentivos_atualizados": 0, "relacionamento": 0}
    linhas = conexao.execute("SELECT mecanismo, fonte, valor FROM incentivos ORDER BY valor").fetchall()
    assert [l["mecanismo"] for l in linhas] == ["LEI_ROUANET", "LEI_ROUANET"]
    assert conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0] == 2


def test_ingerir_de_novo_nao_duplica_e_atualiza_valor(conexao):
    ip.ingerir(conexao, _provider(PAGINAS), "SP")
    alterado = [[_bruto("EMPRESA UM LTDA", "11444777000161", total=9999.0), PAGINAS[0][1]]]
    resumo = ip.ingerir(conexao, _provider(alterado), "SP")
    assert (resumo["empresas_novas"], resumo["incentivos_novos"], resumo["incentivos_atualizados"]) == (0, 0, 2)
    assert conexao.execute("SELECT COUNT(*) FROM incentivos").fetchone()[0] == 2
    assert conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0] == 2
    assert conexao.execute("SELECT valor FROM incentivos WHERE url_fonte LIKE '%11444777000161'").fetchone()[0] == 9999.0


def test_max_paginas_e_paginacao():
    p1 = [_bruto(f"EMPRESA {i} LTDA", None) for i in range(100)]
    p2 = [_bruto("ULTIMA SA", None)]
    assert len(list(_provider([p1, p2]).coletar("SP", max_paginas=1))) == 100
    assert len(list(_provider([p1, p2]).coletar("SP"))) == 101


def test_mecanismos_sem_fonte_confiavel_declaram_o_motivo_e_nao_devolvem_dado():
    provedores = ip.provedores_padrao()
    assert provedores[ip.MECANISMO_ROUANET].status == ip.STATUS_INTEGRADO
    indisponiveis = [p for p in provedores.values() if p.status == ip.STATUS_INDISPONIVEL]
    assert {p.codigo for p in indisponiveis} == {ip.MECANISMO_LPIE, ip.MECANISMO_LIE, ip.MECANISMO_PROAC_ICMS,
                                                  ip.MECANISMO_PRONON_PRONAS, ip.MECANISMO_FIA_IDOSO}
    for p in indisponiveis:
        assert p.investigacao, f"{p.codigo} sem registro do que foi verificado"
        with pytest.raises(ip.IntegracaoIndisponivel, match="Integração ainda não disponível"):
            list(p.coletar("SP"))


def test_migrar_classifica_existentes_sem_perda_e_e_idempotente(conexao):
    eid, _ = banco.obter_ou_criar_empresa(conexao, {"cnpj": "11444777000161", "razao_social": "X", "nome_fantasia": None,
                                                    "cidade": "Guaíra", "estado": "SP", "status": None})
    for i, tipo in enumerate(["Lei Rouanet (incentivo federal à cultura)", "Outro mecanismo qualquer"]):
        conexao.execute(
            """INSERT INTO incentivos (empresa_id, fonte, tipo_incentivo, url_fonte, coletado_em, nivel_confianca)
               VALUES (?, 'SALIC', ?, ?, 'x', 'ALTO')""", (eid, tipo, f"https://x/{i}"))
    conexao.commit()
    ip.migrar(conexao)
    ip.migrar(conexao)
    linhas = conexao.execute("SELECT tipo_incentivo, mecanismo FROM incentivos ORDER BY id").fetchall()
    assert [l["mecanismo"] for l in linhas] == ["LEI_ROUANET", None]  # só classifica o que reconhece
    assert len(linhas) == 2


def test_resumo_por_mecanismo(conexao):
    ip.ingerir(conexao, _provider(PAGINAS), "SP")
    resumo = ip.resumo_por_mecanismo(conexao)
    assert resumo[0]["mecanismo"] == "LEI_ROUANET" and resumo[0]["registros"] == 2 and resumo[0]["empresas"] == 2
    assert resumo[0]["valor_total"] == 1250.5 and resumo[0]["ufs"] == "SP"
