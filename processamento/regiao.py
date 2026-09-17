"""Priorização geográfica (Região IORM).

Substitui o critério antigo, binário ("cidade estratégica sim/não"), por
uma classificação em camadas. Reaproveita o território já cadastrado no
Cérebro da OSC (tabela `osc_territorios`, coluna `tipo`) — nenhuma cidade
nova é inventada aqui; quem decide o que entra em cada camada é a
própria equipe do IORM, cadastrando em Cérebro da OSC -> Território.

Camadas (da mais forte para a mais fraca):
  CIDADE_ATUACAO         osc_territorios tipo='cidade'
                          (já existia antes desta mudança — Ipuã, Guaíra,
                          Miguelópolis, Orlândia continuam vindo daqui)
  REGIAO_PROXIMA         osc_territorios tipo='regiao_proxima'
  INTERESSE_ESTRATEGICO  osc_territorios tipo='interesse_estrategico'
  FORA_DA_REGIAO         qualquer cidade fora das três listas acima

A pontuação de cada camada é a única configuração que precisa mudar para
recalibrar o critério geográfico do IORM Score inteiro — nenhum outro
módulo tem um número mágico de pontuação geográfica espalhado nele."""
from __future__ import annotations

CAMADAS = ["CIDADE_ATUACAO", "REGIAO_PROXIMA", "INTERESSE_ESTRATEGICO", "FORA_DA_REGIAO"]

# Pontos usados no critério geográfico do IORM Score (ver
# processamento/metricas.py::_calcular_score). CIDADE_ATUACAO mantém o
# peso que o critério binário antigo já tinha (25 de 100), para não
# mudar a escala de pontuação de quem já está acostumado com o score.
PONTOS_REGIAO = {
    "CIDADE_ATUACAO": 25,
    "REGIAO_PROXIMA": 15,
    "INTERESSE_ESTRATEGICO": 8,
    "FORA_DA_REGIAO": 0,
}

ROTULOS = {
    "CIDADE_ATUACAO": "Cidade de atuação",
    "REGIAO_PROXIMA": "Região próxima",
    "INTERESSE_ESTRATEGICO": "Interesse estratégico",
    "FORA_DA_REGIAO": "Fora da região",
}

# tipo cadastrado em osc_territorios -> camada de região correspondente.
_TIPO_TERRITORIO_PARA_CAMADA = {
    "cidade": "CIDADE_ATUACAO",
    "regiao_proxima": "REGIAO_PROXIMA",
    "interesse_estrategico": "INTERESSE_ESTRATEGICO",
}


def _agrupar_territorios_por_camada(territorios: list[dict]) -> dict[str, set[str]]:
    grupos: dict[str, set[str]] = {camada: set() for camada in _TIPO_TERRITORIO_PARA_CAMADA.values()}
    for t in territorios or []:
        camada = _TIPO_TERRITORIO_PARA_CAMADA.get(t.get("tipo"))
        if camada and t.get("valor"):
            grupos[camada].add(t["valor"].strip().lower())
    return grupos


def classificar_cidade(cidade: str | None, territorios: list[dict]) -> str:
    """Devolve a camada (uma de CAMADAS) para uma cidade, comparando
    contra o território cadastrado no Cérebro da OSC. Nunca inventa
    proximidade geográfica por conta própria — só usa o que já foi
    cadastrado explicitamente."""
    if not cidade:
        return "FORA_DA_REGIAO"
    cidade_norm = cidade.strip().lower()
    grupos = _agrupar_territorios_por_camada(territorios)
    for camada in ["CIDADE_ATUACAO", "REGIAO_PROXIMA", "INTERESSE_ESTRATEGICO"]:
        if cidade_norm in grupos[camada]:
            return camada
    return "FORA_DA_REGIAO"


def pontos(camada: str) -> int:
    return PONTOS_REGIAO.get(camada, 0)


def rotulo(camada: str) -> str:
    return ROTULOS.get(camada, camada)


def cidades_por_camada(territorios: list[dict]) -> dict[str, list[str]]:
    """Lista (ordenada) de cidades cadastradas em cada camada — usada
    pela navegação de cidade/região da página Oportunidades."""
    grupos = _agrupar_territorios_por_camada(territorios)
    # Mantém a grafia original (com acentos/maiúsculas) em vez do valor normalizado.
    originais: dict[str, list[str]] = {camada: [] for camada in _TIPO_TERRITORIO_PARA_CAMADA.values()}
    vistos: dict[str, set[str]] = {camada: set() for camada in _TIPO_TERRITORIO_PARA_CAMADA.values()}
    for t in territorios or []:
        camada = _TIPO_TERRITORIO_PARA_CAMADA.get(t.get("tipo"))
        valor = (t.get("valor") or "").strip()
        if camada and valor and valor.lower() not in vistos[camada]:
            vistos[camada].add(valor.lower())
            originais[camada].append(valor)
    return {camada: sorted(lista) for camada, lista in originais.items()}
