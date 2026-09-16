"""Registro dos mecanismos de incentivo/captação relevantes para OSCs
brasileiras — a arquitetura multi-fonte pedida para o produto.

Cada mecanismo documenta nome, esfera, órgão responsável, fonte, status
REAL de integração (não "criamos o menu" = "os dados estão vindo"),
método de coleta e a última vez que verificamos essa fonte. Isso evita
que o usuário confunda "módulo existe na tela" com "dado está
realmente integrado" — exatamente o requisito pedido.

Status possíveis (ver paginas/_shared.py -> STATUS_INTEGRACAO):
  INTEGRADA     🟢 dados reais fluindo automaticamente hoje
  PARCIAL       🟡 fonte pública real encontrada, mas sem API/formato
                    estruturado (ex: só PDF) — não integrado ainda
  MANUAL        🔵 cadastro/consulta manual funciona, sem automação
  INDISPONIVEL  🔴 nenhuma fonte pública viável identificada até agora
"""
from __future__ import annotations

MECANISMOS = [
    {
        "nome": "Lei Rouanet (Lei de Incentivo à Cultura)",
        "esfera": "Federal",
        "orgao": "Ministério da Cultura — Secretaria Especial da Cultura",
        "fonte": "SALIC — Sistema de Apoio às Leis de Incentivo à Cultura",
        "url": "https://api.salic.cultura.gov.br/docs",
        "status": "INTEGRADA",
        "metodo_coleta": "API pública oficial (JSON), sem necessidade de chave",
        "campos_disponiveis": "incentivador, proponente, projeto, valor, ano (via /doacoes), UF/cidade",
        "ultima_verificacao": "2026-09-15",
        "observacao": "8.211 empresas de SP coletadas; 27 delas (4 cidades do IORM) com detalhamento por projeto/ano.",
    },
    {
        "nome": "Lei Paulista de Incentivo ao Esporte (LPIE)",
        "esfera": "Estadual (SP)",
        "orgao": "Secretaria de Esportes do Estado de São Paulo",
        "fonte": "Dados Abertos SP",
        "url": "https://dadosabertos.sp.gov.br/dataset/lei-paulista-de-incentivo-ao-esporte",
        "status": "PARCIAL",
        "metodo_coleta": "Planilha/PDF para download — sem API REST nem CSV estruturado encontrado",
        "campos_disponiveis": "projetos em execução (formato não estruturado, requer parser dedicado)",
        "ultima_verificacao": "2026-09-16",
        "observacao": "Fonte oficial real e gratuita, mas em PDF — integração automática não implementada nesta etapa (fica como próximo passo).",
    },
    {
        "nome": "Lei de Incentivo ao Esporte (federal)",
        "esfera": "Federal",
        "orgao": "Ministério do Esporte",
        "fonte": "Painéis de terceiros (ex: Prosas) organizam dados oficiais",
        "url": "https://www.gov.br/esporte/pt-br/acoes-e-programas/lei-de-incentivo-ao-esporte",
        "status": "INDISPONIVEL",
        "metodo_coleta": "Nenhuma API oficial encontrada até agora",
        "campos_disponiveis": "—",
        "ultima_verificacao": "2026-09-14",
        "observacao": "Verificado na etapa anterior do projeto — sem fonte primária estruturada identificada.",
    },
    {
        "nome": "Fundos Municipais da Infância e Adolescência (FIA)",
        "esfera": "Municipal",
        "orgao": "Conselhos Municipais dos Direitos da Criança e do Adolescente",
        "fonte": "Cada conselho publica do seu jeito (sem padrão nacional)",
        "url": None,
        "status": "INDISPONIVEL",
        "metodo_coleta": "Não há fonte única — precisaria mapear conselho por conselho",
        "campos_disponiveis": "—",
        "ultima_verificacao": "2026-09-14",
        "observacao": "Relevante para captação infantil/juvenil do IORM, mas sem dado estruturado disponível.",
    },
    {
        "nome": "Editais e chamadas para OSCs (agregadores)",
        "esfera": "Diversas (pública e privada)",
        "orgao": "Mapa das OSC (IPEA) em parceria com Prosas",
        "fonte": "mapaosc.ipea.gov.br/editais → prosas.com.br/editais",
        "url": "https://mapaosc.ipea.gov.br/editais",
        "status": "MANUAL",
        "metodo_coleta": "Portal de consulta pública (sem API documentada) — cadastro manual no Radar de Editais",
        "campos_disponiveis": "—",
        "ultima_verificacao": "2026-09-16",
        "observacao": "Fonte oficial (IPEA, instituto federal) real para descobrir editais manualmente; sem API para automatizar a busca.",
    },
    {
        "nome": "Doações/patrocínios diretos (fora de lei de incentivo)",
        "esfera": "Privada",
        "orgao": "—",
        "fonte": "Sites institucionais, notícias, relatórios de sustentabilidade",
        "url": None,
        "status": "MANUAL",
        "metodo_coleta": "Módulo de Inteligência de Contatos (busca + cadastro manual)",
        "campos_disponiveis": "presença digital, contatos, evidências ESG/responsabilidade social",
        "ultima_verificacao": "2026-09-16",
        "observacao": "Coberto pelo módulo de enriquecimento — 20+ empresas pesquisadas até agora.",
    },
    {
        "nome": "PRONON (Programa Nacional de Apoio à Atenção Oncológica)",
        "esfera": "Federal",
        "orgao": "Ministério da Saúde",
        "fonte": "Não pesquisado nesta sessão",
        "url": None,
        "status": "INDISPONIVEL",
        "metodo_coleta": "Nenhuma fonte pesquisada ainda",
        "campos_disponiveis": "—",
        "ultima_verificacao": None,
        "observacao": (
            "Mecanismo federal real (renúncia fiscal para ações de prevenção/combate ao câncer), mas fora do "
            "escopo de atuação atual do IORM — cadastrado só para deixar a arquitetura pronta caso o IORM "
            "venha a ter um projeto elegível. Nenhuma fonte de dados foi pesquisada para ele ainda."
        ),
    },
    {
        "nome": "PRONAS/PCD (Programa Nacional de Apoio à Atenção da Pessoa com Deficiência)",
        "esfera": "Federal",
        "orgao": "Ministério da Saúde",
        "fonte": "Não pesquisado nesta sessão",
        "url": None,
        "status": "INDISPONIVEL",
        "metodo_coleta": "Nenhuma fonte pesquisada ainda",
        "campos_disponiveis": "—",
        "ultima_verificacao": None,
        "observacao": "Mesmo caso do PRONON: mecanismo federal real, cadastrado para completar a arquitetura, sem pesquisa de fonte de dados feita ainda.",
    },
    {
        "nome": "Fundos Municipais do Idoso",
        "esfera": "Municipal",
        "orgao": "Conselhos Municipais dos Direitos da Pessoa Idosa",
        "fonte": "Cada conselho publica do seu jeito (sem padrão nacional)",
        "url": None,
        "status": "INDISPONIVEL",
        "metodo_coleta": "Não há fonte única — mesmo problema estrutural do FIA (conselho por conselho)",
        "campos_disponiveis": "—",
        "ultima_verificacao": "2026-09-16",
        "observacao": "Cadastrado para completar a cobertura de mecanismos ligados a conselhos de direitos, mesmo sem uso previsto imediato pelo IORM.",
    },
    {
        "nome": "Outros mecanismos estaduais/municipais (SP e demais estados)",
        "esfera": "Estadual/Municipal",
        "orgao": "Diversos — cada estado/município define os próprios",
        "fonte": "Fragmentada — sem catálogo nacional único",
        "url": None,
        "status": "INDISPONIVEL",
        "metodo_coleta": "Nenhum catálogo único identificado — precisaria mapear estado/município por estado/município",
        "campos_disponiveis": "—",
        "ultima_verificacao": "2026-09-16",
        "observacao": (
            "Registro honesto de uma lacuna estrutural: cada estado/município brasileiro pode ter sua própria "
            "lei de incentivo, sem um catálogo nacional único — diferente da Lei Rouanet, que tem uma API "
            "federal centralizada. Mapear isso exigiria pesquisa dedicada, mecanismo por mecanismo."
        ),
    },
]


def listar_mecanismos() -> list[dict]:
    return MECANISMOS


def contar_por_status() -> dict[str, int]:
    contagem = {"INTEGRADA": 0, "PARCIAL": 0, "MANUAL": 0, "INDISPONIVEL": 0}
    for mecanismo in MECANISMOS:
        contagem[mecanismo["status"]] = contagem.get(mecanismo["status"], 0) + 1
    return contagem
