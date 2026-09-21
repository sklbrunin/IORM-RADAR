"""Consultas agregadas sobre o banco, usadas pela dashboard (app.py).

Este módulo só lê o banco e devolve números/tabelas — nenhuma decisão
sobre como exibir os dados fica aqui (isso é responsabilidade do app.py).
Isso permite testar as contas isoladamente, sem precisar abrir o
Streamlit."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from processamento import regiao

CIDADES_IORM = ["Ipuã", "Guaíra", "Miguelópolis", "Orlândia"]

# Nomes (em minúsculo) de programas do IORM, usados para reconhecer se um
# projeto financiado tem relação direta com o instituto. Lista baseada no
# que está publicado em https://iorm.org.br/ — se um projeto no banco não
# bater com nenhum termo aqui, ele simplesmente não pontua nesse critério
# (não tentamos adivinhar relação).
PROGRAMAS_IORM = [
    "usina da dança",
    "cine energia",
    "tramas do interior",
    "profissionalizando pessoas",
    "nossas bibliotecas",
    "cia. da dança",
    "companhia da dança",
]


def conectar_leitura(caminho_db: Path) -> sqlite3.Connection:
    conexao = sqlite3.connect(caminho_db)
    conexao.row_factory = sqlite3.Row
    return conexao


def estatisticas_gerais(conexao: sqlite3.Connection, cidades_estrategicas: list[str] | None = None) -> dict:
    """Números para os cards do topo da dashboard. Calculados direto no
    banco (não a partir do DataFrame agregado), pra ficar o mais simples
    e verificável possível.

    `cidades_estrategicas` vem do Cérebro da OSC (território cadastrado);
    se não for passado, cai no padrão histórico (4 cidades do IORM) —
    isso mantém compatibilidade com quem chamar esta função sem OSC
    configurada ainda."""
    cidades = cidades_estrategicas or CIDADES_IORM
    total_empresas = conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
    cnpjs_confirmados = conexao.execute(
        "SELECT COUNT(*) FROM empresas WHERE cnpj IS NOT NULL"
    ).fetchone()[0]
    valor_total = conexao.execute("SELECT COALESCE(SUM(valor), 0) FROM incentivos").fetchone()[0]
    doacoes_detalhadas = conexao.execute(
        "SELECT COUNT(*) FROM incentivos WHERE projeto IS NOT NULL"
    ).fetchone()[0]

    marcadores_cidades = ",".join("?" for _ in cidades) if cidades else "''"
    empresas_cidades_iorm = conexao.execute(
        f"SELECT COUNT(*) FROM empresas WHERE cidade IN ({marcadores_cidades})", cidades
    ).fetchone()[0] if cidades else 0

    condicoes_programas = " OR ".join("LOWER(projeto) LIKE ?" for _ in PROGRAMAS_IORM)
    parametros_programas = [f"%{p}%" for p in PROGRAMAS_IORM]
    projetos_iorm = conexao.execute(
        f"SELECT COUNT(DISTINCT projeto) FROM incentivos WHERE {condicoes_programas}",
        parametros_programas,
    ).fetchone()[0]

    return {
        "empresas_mapeadas": total_empresas,
        "cnpjs_confirmados": cnpjs_confirmados,
        "valor_total_incentivos": valor_total or 0,
        "doacoes_detalhadas": doacoes_detalhadas,
        "empresas_cidades_iorm": empresas_cidades_iorm,
        "projetos_relacionados_iorm": projetos_iorm,
    }


def _projeto_ligado_iorm(projetos_concatenados) -> bool:
    if not projetos_concatenados:
        return False
    texto = str(projetos_concatenados).lower()
    return any(programa in texto for programa in PROGRAMAS_IORM)


def _calcular_score(linha: pd.Series) -> int:
    """IORM Score (0-100): pontuação simples e explicável, baseada só nos
    dados que realmente temos hoje. Nenhum critério usa faturamento,
    número de funcionários, ESG ou lucro real — esses dados ainda não
    existem na base.

    Critérios e pesos (somam 100):
      10 - tem histórico de incentivo via Lei Rouanet
      15 - CNPJ confirmado matematicamente
      15 - doação detalhada por projeto/ano disponível (não só agregado)
      25 - critério geográfico ("Região IORM" — ver processamento/regiao.py):
           25 se cidade de atuação, 15 se região próxima, 8 se interesse
           estratégico, 0 fora da região. Camadas e pontos são
           configuráveis num único lugar (regiao.PONTOS_REGIAO), e vêm do
           território cadastrado em Cérebro da OSC — nunca inventados.
      20 - algum projeto financiado bate com um programa do IORM
      15 - valor histórico comprovado (faixas: >=500k / >=100k / >=10k)
    """
    pontos = 0
    if linha["num_incentivos"] > 0:
        pontos += 10
    if linha["cnpj_confirmado"]:
        pontos += 15
    if linha["tem_detalhe"]:
        pontos += 15

    camada_regiao = linha.get("regiao_iorm")
    if pd.notna(camada_regiao):
        pontos += regiao.pontos(camada_regiao)
    elif linha.get("cidade_estrategica"):
        pontos += 25  # compatibilidade: chamado sem classificação de região (ex: código/teste antigo)

    if linha["projeto_iorm"]:
        pontos += 20

    valor = linha["valor_total"] or 0
    if valor >= 500_000:
        pontos += 15
    elif valor >= 100_000:
        pontos += 10
    elif valor >= 10_000:
        pontos += 5

    return int(pontos)


def carregar_empresas(
    conexao: sqlite3.Connection,
    cidades_estrategicas: list[str] | None = None,
    territorios: list[dict] | None = None,
) -> pd.DataFrame:
    """Uma linha por empresa, com métricas agregadas de incentivos e o
    IORM Score já calculado.

    `cidades_estrategicas` (lista simples de nomes) vem do território
    cadastrado no Cérebro da OSC — mantido por compatibilidade. Quando
    `territorios` (lista de {tipo, valor}, também do Cérebro da OSC) é
    informado, o critério geográfico passa a usar as camadas de
    Região IORM (processamento/regiao.py) em vez do binário antigo.
    Sem nenhum dos dois, cai no padrão histórico das 4 cidades do IORM."""
    cidades = cidades_estrategicas or CIDADES_IORM
    linhas = conexao.execute(
        """
        SELECT
            e.id, e.cnpj, e.razao_social, e.nome_fantasia, e.cidade, e.estado, e.status,
            COALESCE(SUM(i.valor), 0) AS valor_total,
            COUNT(i.id) AS num_incentivos,
            SUM(CASE WHEN i.projeto IS NOT NULL THEN 1 ELSE 0 END) AS num_doacoes_detalhadas,
            GROUP_CONCAT(DISTINCT i.projeto) AS projetos,
            MAX(i.nivel_confianca) AS nivel_confianca,
            MAX(i.fonte) AS fonte,
            MAX(i.url_fonte) AS url_fonte,
            MAX(i.coletado_em) AS coletado_em,
            e.relacionamento_iorm, e.relacionamento_tipo, e.relacionamento_fonte, e.relacionamento_em,
            e.reabrir_prospeccao, e.reabrir_justificativa
        FROM empresas e
        LEFT JOIN incentivos i ON i.empresa_id = e.id
        GROUP BY e.id
        """
    ).fetchall()

    df = pd.DataFrame([dict(linha) for linha in linhas])
    if df.empty:
        return df

    df["cnpj_confirmado"] = df["cnpj"].notna()
    if territorios:
        mapa = regiao.mapa_cidade_camada(territorios)
        df["regiao_iorm"] = df["cidade"].apply(lambda c: mapa.get(regiao.normalizar_cidade(c), "FORA_DA_REGIAO") if c else "FORA_DA_REGIAO")
        df["cidade_estrategica"] = df["regiao_iorm"] == "CIDADE_ATUACAO"
    else:
        df["cidade_estrategica"] = df["cidade"].isin(cidades)
        df["regiao_iorm"] = df["cidade_estrategica"].map({True: "CIDADE_ATUACAO", False: "FORA_DA_REGIAO"})
    df["tem_detalhe"] = df["num_doacoes_detalhadas"] > 0
    df["projeto_iorm"] = df["projetos"].apply(_projeto_ligado_iorm)
    # Linha Cruzada: relacionamento persistido (coluna em `empresas`) OU evidência direta nos dados
    # (projeto do IORM), exceto quando a equipe classificou manualmente como "não relacionada".
    manual = df["relacionamento_tipo"].fillna("") == "MANUAL"
    df["linha_cruzada"] = (df["relacionamento_iorm"].fillna(0).astype(int) == 1) | (df["projeto_iorm"] & ~manual)
    df["reabrir_prospeccao"] = df["reabrir_prospeccao"].fillna(0).astype(int) == 1
    # Única definição de prospect (ver processamento/relacionamento.py::eh_prospect).
    df["eh_prospect"] = ~df["linha_cruzada"] | df["reabrir_prospeccao"]
    df["tipo_dado"] = df["tem_detalhe"].map({True: "Detalhado", False: "Agregado"})
    df["score"] = df.apply(_calcular_score, axis=1)

    return df


def contadores_empresas(df: pd.DataFrame) -> dict:
    """Os cinco números da base, cada um com UM significado (a interface nunca deve misturá-los):

      total            — todos os registros de empresas (nada é apagado)
      prospects        — elegíveis para prospecção (fora da Linha Cruzada, ou com prospecção reaberta)
      linha_cruzada    — com relacionamento comprovado com o IORM (ver processamento/relacionamento.py)
      pesquisadas      — PROSPECTS que já passaram por enriquecimento
      nao_pesquisadas  — PROSPECTS ainda sem enriquecimento

    Empresa com prospecção reaberta (justificativa registrada) conta nas duas colunas —
    `total` ≠ `prospects` + `linha_cruzada` só nesse caso, e o campo `reabertas` explica a diferença."""
    if df is None or df.empty:
        return {"total": 0, "prospects": 0, "linha_cruzada": 0, "reabertas": 0, "pesquisadas": 0, "nao_pesquisadas": 0}
    prospects = df["eh_prospect"]
    pesquisado = df["pesquisado"] if "pesquisado" in df.columns else pd.Series(False, index=df.index)
    return {
        "total": int(len(df)),
        "prospects": int(prospects.sum()),
        "linha_cruzada": int(df["linha_cruzada"].sum()),
        "reabertas": int((df["linha_cruzada"] & prospects).sum()),
        "pesquisadas": int((prospects & pesquisado).sum()),
        "nao_pesquisadas": int((prospects & ~pesquisado).sum()),
    }


def doacoes_usina_da_danca(conexao: sqlite3.Connection) -> pd.DataFrame:
    linhas = conexao.execute(
        """
        SELECT e.razao_social AS empresa, i.ano, i.valor, e.cidade, i.projeto,
               i.url_fonte AS fonte
        FROM incentivos i JOIN empresas e ON e.id = i.empresa_id
        WHERE LOWER(i.projeto) LIKE '%usina da dan%'
        ORDER BY i.ano
        """
    ).fetchall()
    return pd.DataFrame([dict(linha) for linha in linhas])


def resumo_cidades_iorm(conexao: sqlite3.Connection, cidades_estrategicas: list[str] | None = None) -> pd.DataFrame:
    """Uma linha por cidade estratégica — inclui a cidade mesmo que não
    tenha nenhuma empresa encontrada (ex: Miguelópolis). Território vem
    do Cérebro da OSC quando disponível."""
    return resumo_por_cidade(conexao, cidades_estrategicas or CIDADES_IORM)


def doacoes_ligadas_ao_iorm(conexao: sqlite3.Connection) -> pd.DataFrame:
    """Todas as doações cujo projeto bate com um programa do próprio IORM
    (ver PROGRAMAS_IORM) — uma linha por (empresa, ano, projeto). Base da
    "Linha Cruzada": empresas com relação direta e já comprovada com o
    IORM, tratadas à parte da lista de prospecção (nunca removidas da
    base — só apresentadas separadamente, ver paginas/oportunidades.py)."""
    condicoes = " OR ".join("LOWER(i.projeto) LIKE ?" for _ in PROGRAMAS_IORM)
    parametros = [f"%{p}%" for p in PROGRAMAS_IORM]
    linhas = conexao.execute(
        f"""
        SELECT e.id AS empresa_id, e.razao_social AS empresa, e.cidade, e.estado,
               i.ano, i.projeto, i.valor, i.url_fonte AS fonte
        FROM incentivos i JOIN empresas e ON e.id = i.empresa_id
        WHERE {condicoes}
        ORDER BY e.razao_social, i.ano DESC
        """,
        parametros,
    ).fetchall()
    return pd.DataFrame([dict(linha) for linha in linhas])


def resumo_por_cidade(conexao: sqlite3.Connection, cidades: list[str]) -> pd.DataFrame:
    """Uma linha por cidade informada — inclui a cidade mesmo sem
    nenhuma empresa encontrada. Função genérica por trás de
    `resumo_cidades_iorm` e da navegação por Região IORM (Oportunidades)."""
    dados = []
    for cidade in cidades:
        linha = conexao.execute(
            """
            SELECT COUNT(DISTINCT e.id) AS empresas, COALESCE(SUM(i.valor), 0) AS valor,
                   COUNT(i.id) AS doacoes
            FROM empresas e LEFT JOIN incentivos i ON i.empresa_id = e.id
            WHERE e.cidade = ?
            """,
            (cidade,),
        ).fetchone()
        dados.append(
            {"cidade": cidade, "empresas": linha["empresas"], "valor": linha["valor"] or 0, "doacoes": linha["doacoes"]}
        )
    return pd.DataFrame(dados)


def historico_empresa(conexao: sqlite3.Connection, empresa_id: int) -> pd.DataFrame:
    linhas = conexao.execute(
        """
        SELECT ano, projeto, valor, fonte, url_fonte, coletado_em, nivel_confianca, tipo_incentivo
        FROM incentivos WHERE empresa_id = ? ORDER BY ano DESC
        """,
        (empresa_id,),
    ).fetchall()
    return pd.DataFrame([dict(linha) for linha in linhas])


def listar_fontes(conexao: sqlite3.Connection) -> pd.DataFrame:
    linhas = conexao.execute("SELECT nome, url, tipo, coletado_em FROM fontes ORDER BY id").fetchall()
    return pd.DataFrame([dict(linha) for linha in linhas])


# ============================================================
# Módulo de enriquecimento (presença digital / contatos / evidências)
# ============================================================

CATEGORIAS_RELEVANCIA_IORM = {"ESG", "SUSTENTABILIDADE", "RESPONSABILIDADE_SOCIAL", "INSTITUTO", "FUNDACAO"}


def _calcular_contactability_score(linha: pd.Series) -> int:
    """Contactability Score (0-100): mede o quão fácil é abordar a
    empresa, com base só em canais e evidências realmente encontrados.
    É uma métrica DIFERENTE do IORM Score (que mede afinidade/histórico).

    Critérios e pesos:
      10 - site oficial encontrado
      20 - e-mail institucional encontrado
      10 - telefone institucional encontrado
      10 - LinkedIn da empresa encontrado
       5 - Instagram oficial encontrado
      15 - evidência de ESG identificada
      15 - evidência de responsabilidade social identificada
      15 - instituto/fundação identificado
      20 - contato profissional relevante confirmado (nível ALTO ou MEDIO)
    Soma pode passar de 100 (múltiplos critérios de evidência) — limitado a 100.
    """
    pontos = 0
    if linha["tem_site"]:
        pontos += 10
    if linha["tem_email_institucional"]:
        pontos += 20
    if linha["tem_telefone_institucional"]:
        pontos += 10
    if linha["tem_linkedin"]:
        pontos += 10
    if linha["tem_instagram"]:
        pontos += 5
    if linha["tem_evidencia_esg"]:
        pontos += 15
    if linha["tem_evidencia_responsabilidade_social"]:
        pontos += 15
    if linha["tem_instituto_fundacao"]:
        pontos += 15
    if linha["tem_contato_profissional_confirmado"]:
        pontos += 20
    return min(100, int(pontos))


def _calcular_prioridade_prospeccao(iorm_score: int, contactability_score: int, tem_relevancia_iorm: bool) -> int:
    """Prioridade de Prospecção (0-100): combina afinidade (IORM Score)
    e facilidade de abordagem (Contactability Score), com um bônus fixo
    quando há evidência direta de abertura institucional (ESG,
    responsabilidade social, instituto ou fundação). Fórmula simples e
    transparente, sem machine learning:

        base = 0.5 * IORM Score + 0.5 * Contactability Score
        prioridade = min(100, base + 10 se houver relevância direta ao IORM)
    """
    base = 0.5 * iorm_score + 0.5 * contactability_score
    bonus = 10 if tem_relevancia_iorm else 0
    return min(100, int(round(base + bonus)))


def carregar_enriquecimento(conexao: sqlite3.Connection) -> pd.DataFrame:
    """Uma linha por empresa que já teve alguma pesquisa de enriquecimento,
    com os flags usados no Contactability Score e nos scores finais."""
    linhas = conexao.execute(
        """
        SELECT DISTINCT empresa_id FROM (
            SELECT empresa_id FROM presenca_digital
            UNION SELECT empresa_id FROM contatos
            UNION SELECT empresa_id FROM evidencias
            UNION SELECT empresa_id FROM historico_pesquisa
        )
        """
    ).fetchall()
    empresa_ids = [linha["empresa_id"] for linha in linhas]
    if not empresa_ids:
        return pd.DataFrame()

    registros = []
    for empresa_id in empresa_ids:
        presencas = conexao.execute(
            "SELECT tipo FROM presenca_digital WHERE empresa_id = ?", (empresa_id,)
        ).fetchall()
        tipos_presenca = {p["tipo"] for p in presencas}

        contatos = conexao.execute(
            "SELECT tipo_contato, nivel_confianca, prioridade FROM contatos WHERE empresa_id = ?", (empresa_id,)
        ).fetchall()
        tipos_contato = {c["tipo_contato"] for c in contatos}
        # "Contato profissional relevante": pessoa com cargo numa das áreas prioritárias (prioridade
        # reconhecida) e confiança ALTO/MEDIO. Sócio/"Administrador" da Receita sem área reconhecida
        # NÃO conta — senão todo CNPJ enriquecido pela Receita ganharia pontos de "responsável".
        tem_contato_confirmado = any(
            c["tipo_contato"] == "PESSOA_CARGO" and c["nivel_confianca"] in ("ALTO", "MEDIO") and c["prioridade"]
            for c in contatos
        )

        evidencias = conexao.execute(
            "SELECT categoria FROM evidencias WHERE empresa_id = ?", (empresa_id,)
        ).fetchall()
        categorias_evidencia = {e["categoria"] for e in evidencias}

        ultima_pesquisa = conexao.execute(
            """SELECT executado_em, status FROM historico_pesquisa
               WHERE empresa_id = ? ORDER BY executado_em DESC LIMIT 1""",
            (empresa_id,),
        ).fetchone()

        registros.append(
            {
                "empresa_id": empresa_id,
                "tem_site": "site" in tipos_presenca,
                "tem_linkedin": "linkedin" in tipos_presenca,
                "tem_instagram": "instagram" in tipos_presenca,
                "tem_facebook": "facebook" in tipos_presenca,
                "tem_youtube": "youtube" in tipos_presenca,
                "tem_email_institucional": bool(
                    {"EMAIL_INSTITUCIONAL", "EMAIL_COMERCIAL", "EMAIL_CONTATO"} & tipos_contato
                ),
                "tem_telefone_institucional": bool(
                    {"TELEFONE_INSTITUCIONAL", "TELEFONE_COMERCIAL", "WHATSAPP_INSTITUCIONAL"} & tipos_contato
                ),
                "tem_contato_profissional_confirmado": tem_contato_confirmado,
                "tem_evidencia_esg": "ESG" in categorias_evidencia,
                "tem_evidencia_responsabilidade_social": bool(
                    {"RESPONSABILIDADE_SOCIAL", "SUSTENTABILIDADE"} & categorias_evidencia
                ),
                "tem_instituto_fundacao": bool({"INSTITUTO", "FUNDACAO"} & categorias_evidencia),
                "tem_relevancia_iorm": bool(CATEGORIAS_RELEVANCIA_IORM & categorias_evidencia),
                "num_contatos": len(contatos),
                "num_redes": len(tipos_presenca),
                "num_evidencias": len(evidencias),
                "ultima_pesquisa_em": ultima_pesquisa["executado_em"] if ultima_pesquisa else None,
                "ultima_pesquisa_status": ultima_pesquisa["status"] if ultima_pesquisa else None,
            }
        )

    df = pd.DataFrame(registros)
    df["contactability_score"] = df.apply(_calcular_contactability_score, axis=1)
    return df


def estatisticas_enriquecimento(conexao: sqlite3.Connection) -> dict:
    empresas_pesquisadas = conexao.execute(
        "SELECT COUNT(DISTINCT empresa_id) FROM historico_pesquisa"
    ).fetchone()[0]
    sites = conexao.execute("SELECT COUNT(*) FROM presenca_digital WHERE tipo = 'site'").fetchone()[0]
    linkedins = conexao.execute("SELECT COUNT(*) FROM presenca_digital WHERE tipo = 'linkedin'").fetchone()[0]
    instagrams = conexao.execute("SELECT COUNT(*) FROM presenca_digital WHERE tipo = 'instagram'").fetchone()[0]
    emails = conexao.execute(
        "SELECT COUNT(*) FROM contatos WHERE tipo_contato IN ('EMAIL_INSTITUCIONAL','EMAIL_COMERCIAL','EMAIL_CONTATO')"
    ).fetchone()[0]
    telefones = conexao.execute(
        "SELECT COUNT(*) FROM contatos WHERE tipo_contato IN "
        "('TELEFONE_INSTITUCIONAL','TELEFONE_COMERCIAL','WHATSAPP_INSTITUCIONAL')"
    ).fetchone()[0]
    contatos_profissionais = conexao.execute(
        "SELECT COUNT(*) FROM contatos WHERE tipo_contato = 'PESSOA_CARGO'"
    ).fetchone()[0]
    empresas_com_esg = conexao.execute(
        "SELECT COUNT(DISTINCT empresa_id) FROM evidencias WHERE categoria = 'ESG'"
    ).fetchone()[0]
    empresas_com_instituto = conexao.execute(
        "SELECT COUNT(DISTINCT empresa_id) FROM evidencias WHERE categoria IN ('INSTITUTO','FUNDACAO')"
    ).fetchone()[0]
    total_evidencias = conexao.execute("SELECT COUNT(*) FROM evidencias").fetchone()[0]

    return {
        "empresas_pesquisadas": empresas_pesquisadas,
        "sites_encontrados": sites,
        "linkedins_encontrados": linkedins,
        "instagrams_encontrados": instagrams,
        "emails_institucionais": emails,
        "telefones_institucionais": telefones,
        "contatos_profissionais": contatos_profissionais,
        "empresas_com_esg": empresas_com_esg,
        "empresas_com_instituto_fundacao": empresas_com_instituto,
        "total_evidencias": total_evidencias,
    }


def presenca_digital_empresa(conexao: sqlite3.Connection, empresa_id: int) -> pd.DataFrame:
    linhas = conexao.execute(
        "SELECT tipo, url, fonte, nivel_confianca FROM presenca_digital WHERE empresa_id = ? ORDER BY tipo",
        (empresa_id,),
    ).fetchall()
    return pd.DataFrame([dict(linha) for linha in linhas])


def contatos_empresa(conexao: sqlite3.Connection, empresa_id: int) -> pd.DataFrame:
    linhas = conexao.execute(
        """SELECT nome, cargo, departamento, tipo_contato, valor, prioridade, fonte, url_fonte, nivel_confianca
           FROM contatos WHERE empresa_id = ? ORDER BY prioridade IS NULL, prioridade""",
        (empresa_id,),
    ).fetchall()
    return pd.DataFrame([dict(linha) for linha in linhas])


def evidencias_empresa(conexao: sqlite3.Connection, empresa_id: int) -> pd.DataFrame:
    linhas = conexao.execute(
        "SELECT categoria, descricao, url, fonte, nivel_confianca FROM evidencias WHERE empresa_id = ? ORDER BY categoria",
        (empresa_id,),
    ).fetchall()
    return pd.DataFrame([dict(linha) for linha in linhas])


_FLAGS_ENRIQUECIMENTO = [
    "tem_site",
    "tem_linkedin",
    "tem_instagram",
    "tem_facebook",
    "tem_youtube",
    "tem_email_institucional",
    "tem_telefone_institucional",
    "tem_contato_profissional_confirmado",
    "tem_evidencia_esg",
    "tem_evidencia_responsabilidade_social",
    "tem_instituto_fundacao",
    "tem_relevancia_iorm",
]


def mesclar_empresas_e_enriquecimento(df_empresas: pd.DataFrame, df_enriquecimento: pd.DataFrame) -> pd.DataFrame:
    """Junta a tabela de empresas (IORM Score) com o que já foi
    pesquisado no módulo de enriquecimento (Contactability Score),
    calculando a Prioridade de Prospecção. Empresas ainda não pesquisadas
    aparecem com contactability_score = 0 (não com dado inventado —
    reflete literalmente "nada encontrado ainda")."""
    if df_empresas.empty:
        return df_empresas

    if df_enriquecimento.empty:
        resultado = df_empresas.copy()
    else:
        resultado = df_empresas.merge(
            df_enriquecimento, left_on="id", right_on="empresa_id", how="left", suffixes=("", "_enq")
        )

    for coluna in _FLAGS_ENRIQUECIMENTO:
        if coluna not in resultado.columns:
            resultado[coluna] = False
        resultado[coluna] = resultado[coluna].fillna(False).astype(bool)

    for coluna in ["num_contatos", "num_redes", "num_evidencias"]:
        if coluna not in resultado.columns:
            resultado[coluna] = 0
        resultado[coluna] = resultado[coluna].fillna(0).astype(int)

    if "contactability_score" not in resultado.columns:
        resultado["contactability_score"] = 0
    resultado["contactability_score"] = resultado["contactability_score"].fillna(0).astype(int)

    if "ultima_pesquisa_em" not in resultado.columns:
        resultado["ultima_pesquisa_em"] = None
    if "ultima_pesquisa_status" not in resultado.columns:
        resultado["ultima_pesquisa_status"] = None
    resultado["pesquisado"] = resultado["ultima_pesquisa_em"].notna()

    resultado["prioridade_prospeccao"] = resultado.apply(
        lambda linha: _calcular_prioridade_prospeccao(
            iorm_score=linha["score"],
            contactability_score=linha["contactability_score"],
            tem_relevancia_iorm=linha["tem_relevancia_iorm"],
        ),
        axis=1,
    )
    return resultado


def contatos_todos_para_exportacao(conexao: sqlite3.Connection) -> pd.DataFrame:
    """Uma linha por contato encontrado, já com dados da empresa e da
    presença digital juntados — pronta para a exportação CSV ("Baixar
    contatos"). Nenhum campo é preenchido com informação inventada:
    quando não há valor, fica vazio/"Não disponível"."""
    contatos = conexao.execute(
        """
        SELECT e.razao_social AS empresa, e.cnpj, e.cidade, e.estado,
               c.nome, c.cargo, c.departamento, c.tipo_contato, c.valor,
               c.prioridade, c.fonte, c.url_fonte, c.coletado_em, c.nivel_confianca,
               c.empresa_id
        FROM contatos c JOIN empresas e ON e.id = c.empresa_id
        ORDER BY e.razao_social
        """
    ).fetchall()
    df = pd.DataFrame([dict(linha) for linha in contatos])
    if df.empty:
        return df

    presencas = conexao.execute("SELECT empresa_id, tipo, url FROM presenca_digital").fetchall()
    df_presenca = pd.DataFrame([dict(linha) for linha in presencas])
    if not df_presenca.empty:
        pivot = df_presenca.pivot_table(index="empresa_id", columns="tipo", values="url", aggfunc="first")
        df = df.merge(pivot, on="empresa_id", how="left")

    for coluna in ("site", "linkedin", "instagram"):
        if coluna not in df.columns:
            df[coluna] = None

    df["email"] = df.apply(
        lambda linha: linha["valor"] if linha["tipo_contato"] in
        ("EMAIL_INSTITUCIONAL", "EMAIL_COMERCIAL", "EMAIL_CONTATO") else None,
        axis=1,
    )
    df["telefone"] = df.apply(
        lambda linha: linha["valor"] if linha["tipo_contato"] in
        ("TELEFONE_INSTITUCIONAL", "TELEFONE_COMERCIAL", "WHATSAPP_INSTITUCIONAL") else None,
        axis=1,
    )
    return df


def historico_pesquisa_empresa(conexao: sqlite3.Connection, empresa_id: int) -> pd.DataFrame:
    linhas = conexao.execute(
        """SELECT executado_em, quantidade_fontes, quantidade_contatos, quantidade_redes,
                  quantidade_evidencias, status, observacoes
           FROM historico_pesquisa WHERE empresa_id = ? ORDER BY executado_em DESC""",
        (empresa_id,),
    ).fetchall()
    return pd.DataFrame([dict(linha) for linha in linhas])
