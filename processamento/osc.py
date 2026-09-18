"""Cérebro da OSC: cadastro institucional da organização (identidade,
territórios, programas, temas, mecanismos, links, documentos e
palavras-chave). Este é o "quem somos" que o Radar de Editais vai usar
para calcular aderência.

Convenção de rastreabilidade: todo registro carrega `origem` —
'FONTE_EXTERNA' (verificado numa fonte pública, com `fonte` preenchida)
ou 'MANUAL' (digitado por alguém da equipe do IORM na própria tela).
Isso deixa claro, na interface, o que é fato verificado e o que é
autodeclarado."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from processamento import geografia

ORIGENS = {"FONTE_EXTERNA", "MANUAL"}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def criar_tabelas(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS osc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            nome_fantasia TEXT,
            cnpj TEXT,
            missao TEXT,
            visao TEXT,
            valores TEXT,
            descricao TEXT,
            ano_fundacao INTEGER,
            natureza_juridica TEXT,
            origem TEXT NOT NULL DEFAULT 'MANUAL',
            fonte TEXT,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS osc_territorios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osc_id INTEGER NOT NULL REFERENCES osc(id),
            tipo TEXT NOT NULL,
            valor TEXT NOT NULL,
            prioritario INTEGER NOT NULL DEFAULT 0,
            origem TEXT NOT NULL DEFAULT 'MANUAL',
            fonte TEXT,
            criado_em TEXT NOT NULL,
            UNIQUE(osc_id, tipo, valor)
        );

        CREATE TABLE IF NOT EXISTS osc_areas_atuacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osc_id INTEGER NOT NULL REFERENCES osc(id),
            tema TEXT NOT NULL,
            origem TEXT NOT NULL DEFAULT 'MANUAL',
            fonte TEXT,
            criado_em TEXT NOT NULL,
            UNIQUE(osc_id, tema)
        );

        CREATE TABLE IF NOT EXISTS osc_programas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osc_id INTEGER NOT NULL REFERENCES osc(id),
            nome TEXT NOT NULL,
            descricao TEXT,
            publico TEXT,
            faixa_etaria TEXT,
            tema TEXT,
            cidade TEXT,
            estado TEXT,
            objetivos TEXT,
            ods TEXT,
            orcamento REAL,
            status TEXT DEFAULT 'ATIVO',
            origem TEXT NOT NULL DEFAULT 'MANUAL',
            fonte TEXT,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS osc_mecanismos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osc_id INTEGER NOT NULL REFERENCES osc(id),
            nome TEXT NOT NULL,
            observacao TEXT,
            origem TEXT NOT NULL DEFAULT 'MANUAL',
            fonte TEXT,
            criado_em TEXT NOT NULL,
            UNIQUE(osc_id, nome)
        );

        CREATE TABLE IF NOT EXISTS osc_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osc_id INTEGER NOT NULL REFERENCES osc(id),
            tipo TEXT NOT NULL,
            url TEXT NOT NULL,
            origem TEXT NOT NULL DEFAULT 'MANUAL',
            fonte TEXT,
            criado_em TEXT NOT NULL,
            UNIQUE(osc_id, tipo, url)
        );

        CREATE TABLE IF NOT EXISTS osc_documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osc_id INTEGER NOT NULL REFERENCES osc(id),
            tipo TEXT NOT NULL,
            nome TEXT NOT NULL,
            descricao TEXT,
            referencia TEXT,
            origem TEXT NOT NULL DEFAULT 'MANUAL',
            criado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS osc_palavras_chave (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osc_id INTEGER NOT NULL REFERENCES osc(id),
            palavra TEXT NOT NULL,
            origem TEXT NOT NULL DEFAULT 'MANUAL',
            fonte TEXT,
            criado_em TEXT NOT NULL,
            UNIQUE(osc_id, palavra)
        );
        """
    )
    conexao.commit()


def semear_organizacao_padrao(conexao: sqlite3.Connection) -> int | None:
    """Se a tabela `osc` estiver vazia, cadastra o IORM com fatos já
    verificados (site iorm.org.br, achados do módulo de enriquecimento e
    o cadastro CNPJ que já existe no próprio banco). Idempotente: não faz
    nada se já existir alguma OSC cadastrada. Devolve o id da OSC (nova
    ou já existente), ou None se a tabela `empresas` ainda não existir."""
    existente = obter_osc_principal(conexao)
    if existente is not None:
        return existente["id"]

    try:
        cnpj_iorm = conexao.execute(
            "SELECT cnpj FROM empresas WHERE razao_social LIKE 'INSTITUTO OSWALDO RIBEIRO%' LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        cnpj_iorm = None

    fonte_site = "Site oficial iorm.org.br"
    osc_id = criar_ou_atualizar_osc(
        conexao, None,
        {
            "nome": "Instituto Oswaldo Ribeiro de Mendonça",
            "nome_fantasia": "IORM",
            "cnpj": cnpj_iorm["cnpj"] if cnpj_iorm else None,
            "missao": "Educação através da arte",
            "visao": None,
            "valores": None,
            "descricao": (
                "Organização de transformação social que atua através da educação pela arte, "
                "cultura, esporte e qualificação profissional, transformando recursos em impacto "
                "social duradouro."
            ),
            "ano_fundacao": 2005,
            "natureza_juridica": None,
            "origem": "FONTE_EXTERNA",
            "fonte": f"{fonte_site}; ano de fundação via colorado.com.br/comunidades; CNPJ do cadastro interno (SALIC)",
        },
    )

    for cidade in ["Ipuã", "Guaíra", "Miguelópolis", "Orlândia"]:
        origem = "FONTE_EXTERNA" if cidade == "Guaíra" else "MANUAL"
        fonte = fonte_site if cidade == "Guaíra" else "Informado pela equipe do IORM"
        adicionar_territorio(conexao, osc_id, "cidade", cidade, prioritario=True, origem=origem, fonte=fonte)
    adicionar_territorio(conexao, osc_id, "estado", "SP", origem="MANUAL", fonte="Inferido do endereço das cidades atendidas")

    for programa in [
        {"nome": "Música: A Linguagem Universal", "tema": "Música"},
        {"nome": "Usina da Dança", "tema": "Dança"},
        {"nome": "Artes e Cultura", "tema": "Teatro e literatura"},
        {"nome": "Cine Energia", "tema": "Cinema", "cidade": "Guaíra"},
        {"nome": "Tramas do Interior", "tema": "Geração de renda", "publico": "mulheres"},
        {"nome": "Profissionalizando Pessoas", "tema": "Qualificação profissional", "objetivos": "Parceria com o SENAC"},
        {"nome": "Nossas Bibliotecas", "tema": "Educação e leitura"},
        {"nome": "Cia. da Dança", "tema": "Dança"},
    ]:
        programa["estado"] = "SP"
        adicionar_programa(conexao, osc_id, {**programa, "origem": "FONTE_EXTERNA", "fonte": fonte_site})

    for tema in ["educação", "arte", "cultura", "música", "dança", "teatro", "literatura", "cinema",
                 "qualificação profissional", "geração de renda"]:
        adicionar_area_atuacao(conexao, osc_id, tema, origem="FONTE_EXTERNA", fonte=fonte_site)

    for palavra in ["educação", "arte", "cultura", "música", "dança", "teatro", "literatura", "cinema",
                     "infância", "juventude", "transformação social", "qualificação profissional"]:
        adicionar_palavra_chave(conexao, osc_id, palavra, origem="FONTE_EXTERNA", fonte=fonte_site)

    adicionar_mecanismo(
        conexao, osc_id, "Lei Rouanet",
        observacao="Confirmado: o IORM aparece como incentivador/proponente nos dados oficiais do SALIC.",
        origem="FONTE_EXTERNA", fonte="Dados internos do IORM Radar (SALIC)",
    )
    adicionar_link(conexao, osc_id, "site", "https://iorm.org.br/", origem="FONTE_EXTERNA", fonte=fonte_site)

    return osc_id


def obter_osc_principal(conexao: sqlite3.Connection) -> sqlite3.Row | None:
    """Por enquanto o sistema tem uma OSC principal (o IORM). A estrutura
    já suporta várias linhas em `osc` para o dia em que o produto virar
    multi-organização — só pegamos a primeira cadastrada."""
    return conexao.execute("SELECT * FROM osc ORDER BY id LIMIT 1").fetchone()


def criar_ou_atualizar_osc(conexao: sqlite3.Connection, osc_id: int | None, dados: dict) -> int:
    agora = _agora()
    if osc_id:
        conexao.execute(
            """UPDATE osc SET nome=?, nome_fantasia=?, cnpj=?, missao=?, visao=?, valores=?,
               descricao=?, ano_fundacao=?, natureza_juridica=?, atualizado_em=? WHERE id=?""",
            (
                dados.get("nome"),
                dados.get("nome_fantasia"),
                dados.get("cnpj"),
                dados.get("missao"),
                dados.get("visao"),
                dados.get("valores"),
                dados.get("descricao"),
                dados.get("ano_fundacao"),
                dados.get("natureza_juridica"),
                agora,
                osc_id,
            ),
        )
        conexao.commit()
        return osc_id

    cursor = conexao.execute(
        """INSERT INTO osc (nome, nome_fantasia, cnpj, missao, visao, valores, descricao,
           ano_fundacao, natureza_juridica, origem, fonte, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dados.get("nome"),
            dados.get("nome_fantasia"),
            dados.get("cnpj"),
            dados.get("missao"),
            dados.get("visao"),
            dados.get("valores"),
            dados.get("descricao"),
            dados.get("ano_fundacao"),
            dados.get("natureza_juridica"),
            dados.get("origem", "MANUAL"),
            dados.get("fonte"),
            agora,
            agora,
        ),
    )
    conexao.commit()
    return cursor.lastrowid


def adicionar_territorio(conexao: sqlite3.Connection, osc_id: int, tipo: str, valor: str,
                          prioritario: bool = False, origem: str = "MANUAL", fonte: str | None = None) -> None:
    conexao.execute(
        """INSERT OR IGNORE INTO osc_territorios (osc_id, tipo, valor, prioritario, origem, fonte, criado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (osc_id, tipo, valor, int(prioritario), origem, fonte, _agora()),
    )
    conexao.commit()


def adicionar_area_atuacao(conexao: sqlite3.Connection, osc_id: int, tema: str,
                            origem: str = "MANUAL", fonte: str | None = None) -> None:
    conexao.execute(
        "INSERT OR IGNORE INTO osc_areas_atuacao (osc_id, tema, origem, fonte, criado_em) VALUES (?, ?, ?, ?, ?)",
        (osc_id, tema, origem, fonte, _agora()),
    )
    conexao.commit()


def adicionar_mecanismo(conexao: sqlite3.Connection, osc_id: int, nome: str, observacao: str | None = None,
                         origem: str = "MANUAL", fonte: str | None = None) -> None:
    conexao.execute(
        """INSERT OR IGNORE INTO osc_mecanismos (osc_id, nome, observacao, origem, fonte, criado_em)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (osc_id, nome, observacao, origem, fonte, _agora()),
    )
    conexao.commit()


def adicionar_link(conexao: sqlite3.Connection, osc_id: int, tipo: str, url: str,
                    origem: str = "MANUAL", fonte: str | None = None) -> None:
    conexao.execute(
        "INSERT OR IGNORE INTO osc_links (osc_id, tipo, url, origem, fonte, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
        (osc_id, tipo, url, origem, fonte, _agora()),
    )
    conexao.commit()


def adicionar_palavra_chave(conexao: sqlite3.Connection, osc_id: int, palavra: str,
                             origem: str = "MANUAL", fonte: str | None = None) -> None:
    palavra = palavra.strip().lower()
    if not palavra:
        return
    conexao.execute(
        "INSERT OR IGNORE INTO osc_palavras_chave (osc_id, palavra, origem, fonte, criado_em) VALUES (?, ?, ?, ?, ?)",
        (osc_id, palavra, origem, fonte, _agora()),
    )
    conexao.commit()


def adicionar_programa(conexao: sqlite3.Connection, osc_id: int, dados: dict) -> int:
    agora = _agora()
    cursor = conexao.execute(
        """INSERT INTO osc_programas
           (osc_id, nome, descricao, publico, faixa_etaria, tema, cidade, estado, objetivos, ods,
            orcamento, status, origem, fonte, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            osc_id,
            dados["nome"],
            dados.get("descricao"),
            dados.get("publico"),
            dados.get("faixa_etaria"),
            dados.get("tema"),
            dados.get("cidade"),
            dados.get("estado"),
            dados.get("objetivos"),
            dados.get("ods"),
            dados.get("orcamento"),
            dados.get("status", "ATIVO"),
            dados.get("origem", "MANUAL"),
            dados.get("fonte"),
            agora,
            agora,
        ),
    )
    conexao.commit()
    return cursor.lastrowid


def adicionar_documento(conexao: sqlite3.Connection, osc_id: int, tipo: str, nome: str,
                         descricao: str | None = None, referencia: str | None = None,
                         origem: str = "MANUAL") -> int:
    cursor = conexao.execute(
        """INSERT INTO osc_documentos (osc_id, tipo, nome, descricao, referencia, origem, criado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (osc_id, tipo, nome, descricao, referencia, origem, _agora()),
    )
    conexao.commit()
    return cursor.lastrowid


def carregar_perfil_completo(conexao: sqlite3.Connection, osc_id: int) -> dict:
    """Junta tudo que o Radar de Editais precisa para calcular aderência,
    num dicionário simples (listas de strings em minúsculo já prontas
    para comparação por palavra-chave)."""
    territorios = [dict(r) for r in conexao.execute(
        "SELECT tipo, valor, prioritario FROM osc_territorios WHERE osc_id = ?", (osc_id,)
    ).fetchall()]
    # Região dos polos (IBGE + ajustes manuais) entra como 'regiao_proxima'; cidade já cadastrada
    # manualmente em outra camada não é duplicada.
    ja_cadastradas = {t["valor"].strip().lower() for t in territorios}
    territorios += [t for t in geografia.territorios_derivados(conexao) if t["valor"].strip().lower() not in ja_cadastradas]
    temas = [r["tema"] for r in conexao.execute(
        "SELECT tema FROM osc_areas_atuacao WHERE osc_id = ?", (osc_id,)
    ).fetchall()]
    palavras_chave = [r["palavra"] for r in conexao.execute(
        "SELECT palavra FROM osc_palavras_chave WHERE osc_id = ?", (osc_id,)
    ).fetchall()]
    programas = [dict(r) for r in conexao.execute(
        "SELECT * FROM osc_programas WHERE osc_id = ?", (osc_id,)
    ).fetchall()]
    mecanismos = [r["nome"] for r in conexao.execute(
        "SELECT nome FROM osc_mecanismos WHERE osc_id = ?", (osc_id,)
    ).fetchall()]

    return {
        "territorios": territorios,
        "cidades": [t["valor"] for t in territorios if t["tipo"] == "cidade"],
        "estados": [t["valor"] for t in territorios if t["tipo"] == "estado"],
        "temas": temas,
        "palavras_chave": palavras_chave,
        "programas": programas,
        "mecanismos": mecanismos,
    }
