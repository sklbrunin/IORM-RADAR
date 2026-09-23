"""Criação das tabelas e funções de gravação no banco SQLite.

Todas as funções de gravação são pensadas para rodar a coleta de novo
sem duplicar dados: empresas são deduplicadas por CNPJ (quando válido),
e incentivos são deduplicados pela URL da fonte (cada registro do SALIC
tem uma URL própria e única)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def conectar(caminho_db: Path) -> sqlite3.Connection:
    caminho_db.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(caminho_db)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON;")
    return conexao


def criar_tabelas(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj TEXT UNIQUE,
            razao_social TEXT NOT NULL,
            nome_fantasia TEXT,
            cidade TEXT,
            estado TEXT,
            status TEXT,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL,
            relacionamento_iorm INTEGER NOT NULL DEFAULT 0,
            relacionamento_tipo TEXT,
            relacionamento_fonte TEXT,
            relacionamento_em TEXT,
            reabrir_prospeccao INTEGER NOT NULL DEFAULT 0,
            reabrir_justificativa TEXT
        );

        CREATE TABLE IF NOT EXISTS incentivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL REFERENCES empresas(id),
            fonte TEXT NOT NULL,
            tipo_incentivo TEXT NOT NULL,
            projeto TEXT,
            ano INTEGER,
            valor REAL,
            uf TEXT,
            cidade TEXT,
            url_fonte TEXT NOT NULL UNIQUE,
            coletado_em TEXT NOT NULL,
            nivel_confianca TEXT NOT NULL,
            mecanismo TEXT
        );

        CREATE TABLE IF NOT EXISTS fontes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            url TEXT NOT NULL,
            tipo TEXT,
            coletado_em TEXT NOT NULL
        );
        """
    )
    conexao.commit()


_COLUNAS_RELACIONAMENTO = {
    "relacionamento_iorm": "INTEGER NOT NULL DEFAULT 0",
    "relacionamento_tipo": "TEXT",
    "relacionamento_fonte": "TEXT",
    "relacionamento_em": "TEXT",
    "reabrir_prospeccao": "INTEGER NOT NULL DEFAULT 0",
    "reabrir_justificativa": "TEXT",
    # v9 — descoberta nacional (processamento/descoberta_empresas.py). Empresas antigas ficam CONFIRMADA (default).
    "dominio": "TEXT",
    "estagio_cadastro": "TEXT NOT NULL DEFAULT 'CONFIRMADA'",
    "possivel_duplicata_de": "INTEGER",
    "origem_descoberta": "TEXT",
}


def migrar_empresas(conexao: sqlite3.Connection) -> None:
    """Migração idempotente: adiciona à tabela `empresas` as colunas da
    classificação de relacionamento (Linha Cruzada) em bancos criados antes
    dela existir. Nunca apaga nem altera dado existente."""
    atuais = {linha["name"] for linha in conexao.execute("PRAGMA table_info(empresas)")}
    for coluna, definicao in _COLUNAS_RELACIONAMENTO.items():
        if coluna not in atuais:
            conexao.execute(f"ALTER TABLE empresas ADD COLUMN {coluna} {definicao}")
    conexao.commit()


def obter_ou_criar_empresa(conexao: sqlite3.Connection, dados: dict) -> tuple[int, bool]:
    """Devolve (id_da_empresa, criada_agora).

    Com CNPJ válido: reaproveita a empresa existente (dedup real).
    Sem CNPJ confirmado: sempre cria uma nova linha — nomes parecidos
    não são fundidos automaticamente nesta versão."""
    agora = datetime.now(timezone.utc).isoformat()

    if dados.get("cnpj"):
        linha = conexao.execute(
            "SELECT id FROM empresas WHERE cnpj = ?", (dados["cnpj"],)
        ).fetchone()
        if linha:
            conexao.execute(
                "UPDATE empresas SET atualizado_em = ? WHERE id = ?", (agora, linha["id"])
            )
            return linha["id"], False

    cursor = conexao.execute(
        """INSERT INTO empresas
           (cnpj, razao_social, nome_fantasia, cidade, estado, status, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dados.get("cnpj"),
            dados["razao_social"],
            dados.get("nome_fantasia"),
            dados.get("cidade"),
            dados.get("estado"),
            dados.get("status"),
            agora,
            agora,
        ),
    )
    return cursor.lastrowid, True


def inserir_ou_atualizar_incentivo(conexao: sqlite3.Connection, dados: dict) -> tuple[int, bool]:
    """Deduplica pela URL da fonte. Se o incentivo já existe, atualiza
    valor/coletado_em (o total pode mudar entre coletas) em vez de criar
    um registro repetido."""
    linha = conexao.execute(
        "SELECT id FROM incentivos WHERE url_fonte = ?", (dados["url_fonte"],)
    ).fetchone()

    if linha:
        conexao.execute(
            """UPDATE incentivos
               SET valor = ?, projeto = ?, ano = ?, coletado_em = ?, nivel_confianca = ?
               WHERE id = ?""",
            (
                dados.get("valor"),
                dados.get("projeto"),
                dados.get("ano"),
                dados["coletado_em"],
                dados["nivel_confianca"],
                linha["id"],
            ),
        )
        return linha["id"], False

    cursor = conexao.execute(
        """INSERT INTO incentivos
           (empresa_id, fonte, tipo_incentivo, projeto, ano, valor, uf, cidade, url_fonte, coletado_em, nivel_confianca,
            mecanismo)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dados["empresa_id"],
            dados["fonte"],
            dados["tipo_incentivo"],
            dados.get("projeto"),
            dados.get("ano"),
            dados.get("valor"),
            dados.get("uf"),
            dados.get("cidade"),
            dados["url_fonte"],
            dados["coletado_em"],
            dados["nivel_confianca"],
            dados.get("mecanismo"),
        ),
    )
    return cursor.lastrowid, True


def criar_tabelas_enriquecimento(conexao: sqlite3.Connection) -> None:
    """Tabelas do módulo de enriquecimento (presença digital, contatos
    institucionais, evidências de ESG/responsabilidade social e o
    histórico de cada rodada de pesquisa). Não mexe nas tabelas do SALIC."""
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS presenca_digital (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL REFERENCES empresas(id),
            tipo TEXT NOT NULL,
            url TEXT NOT NULL,
            fonte TEXT NOT NULL,
            coletado_em TEXT NOT NULL,
            nivel_confianca TEXT NOT NULL,
            verificado INTEGER NOT NULL DEFAULT 0,
            UNIQUE(empresa_id, tipo, url)
        );

        CREATE TABLE IF NOT EXISTS contatos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL REFERENCES empresas(id),
            nome TEXT,
            cargo TEXT,
            departamento TEXT,
            tipo_contato TEXT NOT NULL,
            valor TEXT NOT NULL,
            prioridade TEXT,
            fonte TEXT NOT NULL,
            url_fonte TEXT,
            coletado_em TEXT NOT NULL,
            nivel_confianca TEXT NOT NULL,
            verificado INTEGER NOT NULL DEFAULT 0,
            UNIQUE(empresa_id, tipo_contato, valor)
        );

        CREATE TABLE IF NOT EXISTS evidencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL REFERENCES empresas(id),
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            url TEXT,
            fonte TEXT NOT NULL,
            coletado_em TEXT NOT NULL,
            nivel_confianca TEXT NOT NULL,
            UNIQUE(empresa_id, categoria, descricao)
        );

        CREATE TABLE IF NOT EXISTS historico_pesquisa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL REFERENCES empresas(id),
            executado_em TEXT NOT NULL,
            quantidade_fontes INTEGER NOT NULL DEFAULT 0,
            quantidade_contatos INTEGER NOT NULL DEFAULT 0,
            quantidade_redes INTEGER NOT NULL DEFAULT 0,
            quantidade_evidencias INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            observacoes TEXT
        );
        """
    )
    conexao.commit()


def inserir_ou_atualizar_presenca_digital(conexao: sqlite3.Connection, dados: dict) -> tuple[int, bool]:
    linha = conexao.execute(
        "SELECT id FROM presenca_digital WHERE empresa_id = ? AND tipo = ? AND url = ?",
        (dados["empresa_id"], dados["tipo"], dados["url"]),
    ).fetchone()
    if linha:
        conexao.execute(
            "UPDATE presenca_digital SET coletado_em = ?, nivel_confianca = ? WHERE id = ?",
            (dados["coletado_em"], dados["nivel_confianca"], linha["id"]),
        )
        return linha["id"], False

    cursor = conexao.execute(
        """INSERT INTO presenca_digital (empresa_id, tipo, url, fonte, coletado_em, nivel_confianca, verificado)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            dados["empresa_id"],
            dados["tipo"],
            dados["url"],
            dados["fonte"],
            dados["coletado_em"],
            dados["nivel_confianca"],
            int(dados.get("verificado", False)),
        ),
    )
    return cursor.lastrowid, True


def inserir_ou_atualizar_contato(conexao: sqlite3.Connection, dados: dict) -> tuple[int, bool]:
    """Deduplica por (empresa, tipo_contato, valor normalizado). Se a
    mesma pessoa/canal aparecer de novo, atualiza cargo/fonte em vez de
    criar um registro repetido — mas nunca rebaixa um nível de confiança
    ALTO para algo menor automaticamente."""
    linha = conexao.execute(
        "SELECT id, nivel_confianca FROM contatos WHERE empresa_id = ? AND tipo_contato = ? AND valor = ?",
        (dados["empresa_id"], dados["tipo_contato"], dados["valor"]),
    ).fetchone()

    if linha:
        nivel_novo = dados["nivel_confianca"]
        if _RANQUE_CONFIANCA.get(nivel_novo, 0) < _RANQUE_CONFIANCA.get(linha["nivel_confianca"], 0):
            nivel_novo = linha["nivel_confianca"]
        conexao.execute(
            """UPDATE contatos SET nome = COALESCE(?, nome), cargo = COALESCE(?, cargo),
               departamento = COALESCE(?, departamento), prioridade = COALESCE(?, prioridade),
               coletado_em = ?, nivel_confianca = ? WHERE id = ?""",
            (
                dados.get("nome"),
                dados.get("cargo"),
                dados.get("departamento"),
                dados.get("prioridade"),
                dados["coletado_em"],
                nivel_novo,
                linha["id"],
            ),
        )
        return linha["id"], False

    cursor = conexao.execute(
        """INSERT INTO contatos
           (empresa_id, nome, cargo, departamento, tipo_contato, valor, prioridade, fonte, url_fonte,
            coletado_em, nivel_confianca, verificado)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dados["empresa_id"],
            dados.get("nome"),
            dados.get("cargo"),
            dados.get("departamento"),
            dados["tipo_contato"],
            dados["valor"],
            dados.get("prioridade"),
            dados["fonte"],
            dados.get("url_fonte"),
            dados["coletado_em"],
            dados["nivel_confianca"],
            int(dados.get("verificado", False)),
        ),
    )
    return cursor.lastrowid, True


_RANQUE_CONFIANCA = {"NAO_CONFIRMADO": 0, "BAIXO": 1, "MEDIO": 2, "ALTO": 3}


def inserir_ou_atualizar_evidencia(conexao: sqlite3.Connection, dados: dict) -> tuple[int, bool]:
    linha = conexao.execute(
        "SELECT id FROM evidencias WHERE empresa_id = ? AND categoria = ? AND descricao = ?",
        (dados["empresa_id"], dados["categoria"], dados["descricao"]),
    ).fetchone()
    if linha:
        conexao.execute(
            "UPDATE evidencias SET url = ?, coletado_em = ?, nivel_confianca = ? WHERE id = ?",
            (dados.get("url"), dados["coletado_em"], dados["nivel_confianca"], linha["id"]),
        )
        return linha["id"], False

    cursor = conexao.execute(
        """INSERT INTO evidencias (empresa_id, categoria, descricao, url, fonte, coletado_em, nivel_confianca)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            dados["empresa_id"],
            dados["categoria"],
            dados["descricao"],
            dados.get("url"),
            dados["fonte"],
            dados["coletado_em"],
            dados["nivel_confianca"],
        ),
    )
    return cursor.lastrowid, True


def registrar_pesquisa(conexao: sqlite3.Connection, dados: dict) -> int:
    cursor = conexao.execute(
        """INSERT INTO historico_pesquisa
           (empresa_id, executado_em, quantidade_fontes, quantidade_contatos, quantidade_redes,
            quantidade_evidencias, status, observacoes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dados["empresa_id"],
            dados["executado_em"],
            dados.get("quantidade_fontes", 0),
            dados.get("quantidade_contatos", 0),
            dados.get("quantidade_redes", 0),
            dados.get("quantidade_evidencias", 0),
            dados["status"],
            dados.get("observacoes"),
        ),
    )
    return cursor.lastrowid


def registrar_fonte(conexao: sqlite3.Connection, dados: dict) -> int:
    """Catálogo de fontes integradas ao projeto (uma linha por fonte,
    não por registro coletado). A evidência de cada registro individual
    fica em incentivos.url_fonte / coletado_em / nivel_confianca."""
    linha = conexao.execute("SELECT id FROM fontes WHERE nome = ?", (dados["nome"],)).fetchone()
    if linha:
        conexao.execute(
            "UPDATE fontes SET url = ?, tipo = ?, coletado_em = ? WHERE id = ?",
            (dados["url"], dados.get("tipo"), dados["coletado_em"], linha["id"]),
        )
        return linha["id"]

    cursor = conexao.execute(
        "INSERT INTO fontes (nome, url, tipo, coletado_em) VALUES (?, ?, ?, ?)",
        (dados["nome"], dados["url"], dados.get("tipo"), dados["coletado_em"]),
    )
    return cursor.lastrowid
