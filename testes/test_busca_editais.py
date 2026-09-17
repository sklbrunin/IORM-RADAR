from processamento import busca_editais, busca_providers

PERFIL = {
    "cidades": ["Guaíra", "Ipuã"],
    "estados": ["SP"],
    "temas": ["cultura", "educação"],
    "palavras_chave": ["arte"],
    "programas": [],
}


class ProviderFalso(busca_providers.SearchProvider):
    nome = "ProviderFalso"

    def __init__(self, resultados):
        self._resultados = resultados

    def disponivel(self):
        return True

    def buscar(self, query, num_resultados=5):
        return self._resultados


def test_montar_consultas_usa_territorio_e_temas():
    consultas = busca_editais.montar_consultas(PERFIL)
    assert len(consultas) == 3  # uma por fonte confiável
    assert any("SP" in c for c in consultas)
    assert any("cultura" in c for c in consultas)
    assert all("site:" in c for c in consultas)


def test_montar_consultas_sem_perfil_nao_quebra():
    consultas = busca_editais.montar_consultas({})
    assert len(consultas) == 3


def test_extrair_data_formato_iso():
    assert busca_editais._extrair_data("Inscrições até 2026-12-31.") == "2026-12-31"


def test_extrair_data_formato_br():
    assert busca_editais._extrair_data("Prazo: 31/12/2026.") == "2026-12-31"


def test_extrair_data_ausente():
    assert busca_editais._extrair_data("Sem nenhuma data aqui.") is None


def test_sem_provider_real_devolve_sem_provider():
    resultado = busca_editais.buscar_editais(PERFIL, provider=busca_providers.FilaManualProvider())
    assert resultado["status"] == "SEM_PROVIDER"
    assert resultado["candidatos"] == []


def test_buscar_editais_devolve_candidatos_com_situacao_nao_confirmada():
    provider = ProviderFalso(
        [busca_providers.ResultadoBusca(titulo="Edital de Cultura 2026", url="https://gov.br/edital-x", trecho="Apoio a projetos culturais.")]
    )
    resultado = busca_editais.buscar_editais(PERFIL, provider=provider)
    assert resultado["status"] == "OK"
    assert len(resultado["candidatos"]) == 1  # mesma URL nas 3 consultas -> deduplicado
    candidato = resultado["candidatos"][0]
    assert candidato["situacao_inscricao"] == "NAO_CONFIRMADO"
    assert candidato["origem_descoberta"] == "AUTOMATICA"
    assert candidato["url"] == "https://gov.br/edital-x"


def test_buscar_editais_deduplica_por_url():
    resultado_unico = [busca_providers.ResultadoBusca(titulo="Edital A", url="https://gov.br/a", trecho="")]

    class ProviderRepetido(busca_providers.SearchProvider):
        nome = "ProviderRepetido"

        def disponivel(self):
            return True

        def buscar(self, query, num_resultados=5):
            return resultado_unico  # mesma URL em toda consulta

    resultado = busca_editais.buscar_editais(PERFIL, provider=ProviderRepetido())
    assert len(resultado["candidatos"]) == 1


def test_buscar_editais_com_data_no_texto_classifica_situacao():
    provider = ProviderFalso(
        [busca_providers.ResultadoBusca(titulo="Edital Y", url="https://gov.br/y", trecho="Inscrições até 31/12/2099.")]
    )
    resultado = busca_editais.buscar_editais(PERFIL, provider=provider)
    assert resultado["candidatos"][0]["situacao_inscricao"] == "ABERTO"


def test_buscar_editais_registra_erro_do_provider():
    class ProviderComErro(busca_providers.SearchProvider):
        nome = "ProviderComErro"

        def disponivel(self):
            return True

        def buscar(self, query, num_resultados=5):
            self.ultimo_erro = "Falha simulada"
            return []

    resultado = busca_editais.buscar_editais(PERFIL, provider=ProviderComErro())
    assert resultado["status"] == "OK"
    assert len(resultado["erros"]) == 3
    assert resultado["candidatos"] == []
