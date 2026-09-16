from unittest.mock import Mock, patch

from processamento import busca_providers

# Resposta de exemplo fiel ao formato documentado publicamente pelo
# SerpApi (https://serpapi.com/search-api) para engine=google — usada
# para validar a lógica de leitura sem depender de uma chave real.
RESPOSTA_EXEMPLO_SERPAPI = {
    "search_metadata": {"status": "Success"},
    "organic_results": [
        {
            "position": 1,
            "title": "Mina Mercantil Industrial e Agrícola - Site Oficial",
            "link": "https://www.minamercantil.com.br",
            "snippet": "Empresa comprometida com a Agenda 2030 e sustentabilidade.",
        },
        {
            "position": 2,
            "title": "Mina Mercantil no LinkedIn",
            "link": "https://br.linkedin.com/company/minamercantil",
            "snippet": "Página oficial da empresa no LinkedIn.",
        },
        {"position": 3, "title": "Sem link", "snippet": "Resultado malformado, sem 'link' — deve ser ignorado"},
    ],
}


def test_serpapi_provider_indisponivel_sem_chave():
    provider = busca_providers.SerpApiProvider(api_key=None)
    assert provider.disponivel() is False
    assert provider.buscar("qualquer coisa") == []


def test_serpapi_provider_disponivel_com_chave():
    provider = busca_providers.SerpApiProvider(api_key="chave-de-teste")
    assert provider.disponivel() is True


def test_parse_resposta_le_resultados_organicos_corretamente():
    resultados = busca_providers.SerpApiProvider._parse_resposta(RESPOSTA_EXEMPLO_SERPAPI, num_resultados=5)
    assert len(resultados) == 2  # o terceiro item (sem link) é descartado
    assert resultados[0].titulo == "Mina Mercantil Industrial e Agrícola - Site Oficial"
    assert resultados[0].url == "https://www.minamercantil.com.br"
    assert resultados[1].url == "https://br.linkedin.com/company/minamercantil"


def test_parse_resposta_respeita_num_resultados():
    resultados = busca_providers.SerpApiProvider._parse_resposta(RESPOSTA_EXEMPLO_SERPAPI, num_resultados=1)
    assert len(resultados) == 1


def test_parse_resposta_sem_organic_results_nao_quebra():
    assert busca_providers.SerpApiProvider._parse_resposta({}, num_resultados=5) == []


@patch("processamento.busca_providers.requests.get")
def test_buscar_faz_requisicao_e_devolve_resultados(mock_get):
    mock_resposta = Mock()
    mock_resposta.json.return_value = RESPOSTA_EXEMPLO_SERPAPI
    mock_resposta.raise_for_status.return_value = None
    mock_get.return_value = mock_resposta

    provider = busca_providers.SerpApiProvider(api_key="chave-de-teste")
    resultados = provider.buscar("Mina Mercantil Guaíra SP")

    assert len(resultados) == 2
    mock_get.assert_called_once()
    parametros_chamada = mock_get.call_args.kwargs["params"]
    assert parametros_chamada["q"] == "Mina Mercantil Guaíra SP"
    assert parametros_chamada["gl"] == "br"
    assert parametros_chamada["api_key"] == "chave-de-teste"


@patch("processamento.busca_providers.requests.get")
def test_buscar_falha_de_rede_devolve_lista_vazia_sem_quebrar(mock_get):
    import requests

    mock_get.side_effect = requests.ConnectionError("falha simulada")
    provider = busca_providers.SerpApiProvider(api_key="chave-de-teste")
    assert provider.buscar("qualquer coisa") == []


def test_fila_manual_provider_sempre_disponivel_mas_nao_busca():
    provider = busca_providers.FilaManualProvider()
    assert provider.disponivel() is True
    assert provider.buscar("qualquer coisa") == []


def test_obter_provider_ativo_sem_chave_cai_no_fallback(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    provider = busca_providers.obter_provider_ativo()
    assert isinstance(provider, busca_providers.FilaManualProvider)


def test_obter_provider_ativo_com_chave_usa_serpapi(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "chave-de-teste")
    provider = busca_providers.obter_provider_ativo()
    assert isinstance(provider, busca_providers.SerpApiProvider)


@patch("processamento.busca_providers.requests.get")
def test_buscar_chave_invalida_define_ultimo_erro_amigavel(mock_get):
    mock_resposta = Mock()
    mock_resposta.status_code = 401
    mock_get.return_value = mock_resposta

    provider = busca_providers.SerpApiProvider(api_key="chave-invalida")
    resultados = provider.buscar("qualquer coisa")

    assert resultados == []
    assert provider.ultimo_erro is not None
    assert "chave" in provider.ultimo_erro.lower()


@patch("processamento.busca_providers.requests.get")
def test_buscar_limite_atingido_define_ultimo_erro_amigavel(mock_get):
    mock_resposta = Mock()
    mock_resposta.status_code = 429
    mock_get.return_value = mock_resposta

    provider = busca_providers.SerpApiProvider(api_key="chave-de-teste")
    resultados = provider.buscar("qualquer coisa")

    assert resultados == []
    assert "limite" in provider.ultimo_erro.lower()


@patch("processamento.busca_providers.requests.get")
def test_buscar_timeout_define_ultimo_erro_amigavel(mock_get):
    import requests

    mock_get.side_effect = requests.Timeout("demorou demais")
    provider = busca_providers.SerpApiProvider(api_key="chave-de-teste")
    resultados = provider.buscar("qualquer coisa")

    assert resultados == []
    assert "timeout" in provider.ultimo_erro.lower()


@patch("processamento.busca_providers.requests.get")
def test_buscar_corpo_com_campo_error_define_ultimo_erro(mock_get):
    mock_resposta = Mock()
    mock_resposta.status_code = 200
    mock_resposta.raise_for_status.return_value = None
    mock_resposta.json.return_value = {"error": "Invalid API key."}
    mock_get.return_value = mock_resposta

    provider = busca_providers.SerpApiProvider(api_key="chave-de-teste")
    resultados = provider.buscar("qualquer coisa")

    assert resultados == []
    assert "Invalid API key" in provider.ultimo_erro


@patch("processamento.busca_providers.requests.get")
def test_buscar_sucesso_limpa_ultimo_erro_de_tentativa_anterior(mock_get):
    mock_resposta = Mock()
    mock_resposta.status_code = 200
    mock_resposta.raise_for_status.return_value = None
    mock_resposta.json.return_value = RESPOSTA_EXEMPLO_SERPAPI
    mock_get.return_value = mock_resposta

    provider = busca_providers.SerpApiProvider(api_key="chave-de-teste")
    provider.ultimo_erro = "erro de uma tentativa anterior"
    resultados = provider.buscar("qualquer coisa")

    assert len(resultados) == 2
    assert provider.ultimo_erro is None
