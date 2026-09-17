from processamento import regiao

TERRITORIOS = [
    {"tipo": "cidade", "valor": "Guaíra"},
    {"tipo": "cidade", "valor": "Ipuã"},
    {"tipo": "regiao_proxima", "valor": "Barretos"},
    {"tipo": "interesse_estrategico", "valor": "Ribeirão Preto"},
    {"tipo": "estado", "valor": "SP"},
]


def test_classificar_cidade_de_atuacao():
    assert regiao.classificar_cidade("Guaíra", TERRITORIOS) == "CIDADE_ATUACAO"


def test_classificar_cidade_e_case_insensitive():
    assert regiao.classificar_cidade("guaíra", TERRITORIOS) == "CIDADE_ATUACAO"
    assert regiao.classificar_cidade("GUAÍRA", TERRITORIOS) == "CIDADE_ATUACAO"


def test_classificar_regiao_proxima():
    assert regiao.classificar_cidade("Barretos", TERRITORIOS) == "REGIAO_PROXIMA"


def test_classificar_interesse_estrategico():
    assert regiao.classificar_cidade("Ribeirão Preto", TERRITORIOS) == "INTERESSE_ESTRATEGICO"


def test_classificar_fora_da_regiao():
    assert regiao.classificar_cidade("Osasco", TERRITORIOS) == "FORA_DA_REGIAO"


def test_classificar_sem_cidade():
    assert regiao.classificar_cidade(None, TERRITORIOS) == "FORA_DA_REGIAO"


def test_classificar_sem_territorios_cadastrados():
    assert regiao.classificar_cidade("Guaíra", []) == "FORA_DA_REGIAO"


def test_tipo_estado_nao_conta_como_cidade():
    # "SP" está cadastrado como tipo='estado', não deve classificar uma cidade chamada "SP"
    assert regiao.classificar_cidade("SP", TERRITORIOS) == "FORA_DA_REGIAO"


def test_pontos_seguem_ordem_decrescente():
    assert regiao.pontos("CIDADE_ATUACAO") > regiao.pontos("REGIAO_PROXIMA") > regiao.pontos("INTERESSE_ESTRATEGICO") > regiao.pontos("FORA_DA_REGIAO")


def test_pontos_camada_desconhecida_e_zero():
    assert regiao.pontos("CAMADA_INEXISTENTE") == 0


def test_rotulo_tem_texto_para_todas_as_camadas():
    for camada in regiao.CAMADAS:
        assert regiao.rotulo(camada) and regiao.rotulo(camada) != camada.upper()


def test_cidades_por_camada_agrupa_corretamente():
    grupos = regiao.cidades_por_camada(TERRITORIOS)
    assert grupos["CIDADE_ATUACAO"] == ["Guaíra", "Ipuã"]
    assert grupos["REGIAO_PROXIMA"] == ["Barretos"]
    assert grupos["INTERESSE_ESTRATEGICO"] == ["Ribeirão Preto"]


def test_cidades_por_camada_sem_duplicatas():
    territorios = TERRITORIOS + [{"tipo": "cidade", "valor": "guaíra"}]  # mesma cidade, grafia diferente
    grupos = regiao.cidades_por_camada(territorios)
    assert grupos["CIDADE_ATUACAO"] == ["Guaíra", "Ipuã"]
