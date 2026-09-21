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


def test_prazo_no_texto_vira_sugestao_com_trecho_e_nunca_abre_o_edital_sozinho():
    provider = ProviderFalso(
        [busca_providers.ResultadoBusca(titulo="Edital Y", url="https://gov.br/y", trecho="Inscrições até 31/12/2099.")]
    )
    candidato = busca_editais.buscar_editais(PERFIL, provider=provider)["candidatos"][0]
    assert candidato["situacao_inscricao"] == "NAO_CONFIRMADO"
    assert candidato["data_encerramento"] is None  # só a equipe confirma o prazo
    assert candidato["prazo_sugerido"] == "2099-12-31" and "31/12/2099" in candidato["prazo_sugerido_trecho"]


def test_data_solta_no_trecho_nao_e_tratada_como_prazo():
    provider = ProviderFalso(
        [busca_providers.ResultadoBusca(titulo="Edital Z", url="https://gov.br/z", trecho="Publicado em 10/01/2026 pela secretaria.")]
    )
    candidato = busca_editais.buscar_editais(PERFIL, provider=provider)["candidatos"][0]
    assert candidato["prazo_sugerido"] is None and candidato["data_encerramento"] is None

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

def test_territorio_do_candidato_nao_e_copiado_do_perfil_da_osc():
    """Regressão: a busca preenchia o território do edital com as cidades da própria OSC, fabricando 10/10 de aderência territorial."""
    provider = ProviderFalso([busca_providers.ResultadoBusca(titulo="Edital W", url="https://gov.br/w", trecho="Apoio a projetos.")])
    candidato = busca_editais.buscar_editais(PERFIL, provider=provider)["candidatos"][0]
    assert candidato["territorio"] is None
    from processamento import editais
    r = editais.calcular_aderencia(candidato, {"temas": ["cultura"], "palavras_chave": [], "cidades": ["Guaíra"], "estados": ["SP"], "programas": []})
    assert r["nota_territorio"] is None  # "Não identificado na fonte", não 10/10
