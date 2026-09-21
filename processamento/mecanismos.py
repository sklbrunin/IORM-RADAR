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
        "observacao": (
            "Provedor integrado (processamento/incentivos_providers.py; coleta por UF com --uf). SP completo e parte de MG "
            "já estão na base; as empresas das 4 cidades do IORM têm detalhamento por projeto/ano."
        ),
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
        "ultima_verificacao": "2026-09-18",
        "observacao": (
            "Verificado em 18/09/2026: o dataset traz um único PDF de PROJETOS em execução, sem os incentivadores "
            "(empresas). Por isso não alimenta a base de empresas — integração não disponível com esta fonte."
        ),
    },
    {
        "nome": "ProAC ICMS (incentivo estadual à cultura — SP)",
        "esfera": "Estadual (SP)",
        "orgao": "Secretaria da Cultura, Economia e Indústria Criativas do Estado de SP",
        "fonte": "Portais de consulta de projetos (fomentocultsp / vitrine de projetos)",
        "url": "https://www.cultura.sp.gov.br/sec_cultura/Fomento/ProAC_ICMS",
        "status": "INDISPONIVEL",
        "metodo_coleta": "Nenhum arquivo/API com empresas incentivadoras localizado",
        "campos_disponiveis": "—",
        "ultima_verificacao": "2026-09-18",
        "observacao": (
            "Verificado em 18/09/2026: a página do programa só remete a portais de consulta; o dataset FOMENTOS do Dados "
            "Abertos SP não tem URL de arquivo; a lista mensal de empresas habilitadas não foi encontrada em formato "
            "estruturado. Relevante para captação cultural do IORM em SP — reavaliar se a Secretaria publicar a base."
        ),
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
        "ultima_verificacao": "2026-09-18",
        "observacao": (
            "Reverificado em 18/09/2026: o catálogo dados.gov.br respondeu HTTP 401 (exige token) e o painel oficial de "
            "transparência é interativo. O painel com patrocinadores é do Prosas (terceiro, não oficial). Se a equipe "
            "obtiver um token do dados.gov.br, dá para reavaliar."
        ),
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
        "ultima_verificacao": "2026-09-18",
        "observacao": (
            "Relevante para captação infantil/juvenil do IORM. Verificado em 18/09/2026: as doações são declaradas à "
            "Receita (DBF) por cada fundo/conselho; não existe base pública nacional de doadores por empresa."
        ),
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
        "fonte": "Listas de projetos aprovados (DOU / Transferegov)",
        "url": "https://www.gov.br/saude/pt-br/se/pronon-e-pronas-pcd",
        "status": "INDISPONIVEL",
        "metodo_coleta": "Sem base pública de doadores (a página de doações exige autenticação)",
        "campos_disponiveis": "—",
        "ultima_verificacao": "2026-09-18",
        "observacao": (
            "Mecanismo federal real (saúde/oncologia), fora do escopo de atuação atual do IORM. Verificado em "
            "18/09/2026: o Ministério publica projetos aprovados, não os doadores (empresas) — não alimenta a base."
        ),
    },
    {
        "nome": "PRONAS/PCD (Programa Nacional de Apoio à Atenção da Pessoa com Deficiência)",
        "esfera": "Federal",
        "orgao": "Ministério da Saúde",
        "fonte": "Listas de projetos aprovados (DOU / Transferegov)",
        "url": "https://www.gov.br/saude/pt-br/se/pronon-e-pronas-pcd",
        "status": "INDISPONIVEL",
        "metodo_coleta": "Sem base pública de doadores (a página de doações exige autenticação)",
        "campos_disponiveis": "—",
        "ultima_verificacao": "2026-09-18",
        "observacao": "Mesmo caso do PRONON (mesmo programa do Ministério da Saúde): só há lista de projetos aprovados, não de doadores.",
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
