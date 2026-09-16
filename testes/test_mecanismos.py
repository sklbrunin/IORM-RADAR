from processamento import mecanismos

STATUS_VALIDOS = {"INTEGRADA", "PARCIAL", "MANUAL", "INDISPONIVEL"}


def test_todos_mecanismos_tem_status_valido():
    for mecanismo in mecanismos.listar_mecanismos():
        assert mecanismo["status"] in STATUS_VALIDOS


def test_todos_mecanismos_tem_campos_obrigatorios():
    campos_obrigatorios = {"nome", "esfera", "orgao", "fonte", "status", "metodo_coleta", "ultima_verificacao"}
    for mecanismo in mecanismos.listar_mecanismos():
        assert campos_obrigatorios.issubset(mecanismo.keys())


def test_lei_rouanet_esta_marcada_como_integrada():
    rouanet = next(m for m in mecanismos.listar_mecanismos() if "Rouanet" in m["nome"])
    assert rouanet["status"] == "INTEGRADA"


def test_contar_por_status_soma_o_total():
    contagem = mecanismos.contar_por_status()
    assert sum(contagem.values()) == len(mecanismos.listar_mecanismos())
