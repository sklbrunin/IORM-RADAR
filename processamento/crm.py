"""CRM de Captação: pipeline de oportunidades, interações e follow-ups.

Uma oportunidade pode (mas não precisa) estar ligada a uma empresa do
Radar (`empresa_id`) e a um contato já encontrado pelo enriquecimento
(`contato_id`) — sem duplicar esses cadastros."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

ESTAGIOS = [
    "Prospect",
    "Primeiro contato",
    "Em conversa",
    "Reunião",
    "Projeto apresentado",
    "Proposta enviada",
    "Negociação",
    "Fechado — ganho",
    "Fechado — perdido",
]

ESTAGIOS_ABERTOS = [e for e in ESTAGIOS if not e.startswith("Fechado")]

TIPOS_INTERACAO = ["ligacao", "whatsapp", "email", "reuniao", "linkedin", "evento", "outro"]

PRIORIDADES = ["ALTA", "MEDIA", "BAIXA"]


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def criar_tabelas(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS crm_oportunidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER REFERENCES empresas(id),
            contato_id INTEGER REFERENCES contatos(id),
            titulo TEXT NOT NULL,
            estagio TEXT NOT NULL DEFAULT 'Prospect',
            valor_potencial REAL,
            mecanismo TEXT,
            probabilidade INTEGER,
            responsavel TEXT,
            proxima_acao_data TEXT,
            proxima_acao_descricao TEXT,
            proxima_acao_prioridade TEXT,
            programa_relacionado TEXT,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS crm_interacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            oportunidade_id INTEGER NOT NULL REFERENCES crm_oportunidades(id),
            tipo TEXT NOT NULL,
            data TEXT NOT NULL,
            responsavel TEXT,
            descricao TEXT,
            resultado TEXT,
            proxima_acao TEXT,
            criado_em TEXT NOT NULL
        );
        """
    )
    conexao.commit()


def migrar_colunas_novas(conexao: sqlite3.Connection) -> None:
    """Migração segura e idempotente: adiciona colunas novas a tabelas já
    existentes sem apagar nada. SQLite não tem "ADD COLUMN IF NOT EXISTS",
    então checamos o schema atual antes de tentar."""
    colunas_atuais = {linha["name"] for linha in conexao.execute("PRAGMA table_info(crm_oportunidades)")}
    if "programa_relacionado" not in colunas_atuais:
        conexao.execute("ALTER TABLE crm_oportunidades ADD COLUMN programa_relacionado TEXT")
        conexao.commit()


def criar_oportunidade(conexao: sqlite3.Connection, dados: dict) -> int:
    agora = _agora()
    estagio = dados.get("estagio", "Prospect")
    if estagio not in ESTAGIOS:
        estagio = "Prospect"
    cursor = conexao.execute(
        """INSERT INTO crm_oportunidades
           (empresa_id, contato_id, titulo, estagio, valor_potencial, mecanismo, probabilidade,
            responsavel, proxima_acao_data, proxima_acao_descricao, proxima_acao_prioridade,
            programa_relacionado, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dados.get("empresa_id"),
            dados.get("contato_id"),
            dados["titulo"],
            estagio,
            dados.get("valor_potencial"),
            dados.get("mecanismo"),
            dados.get("probabilidade"),
            dados.get("responsavel"),
            dados.get("proxima_acao_data"),
            dados.get("proxima_acao_descricao"),
            dados.get("proxima_acao_prioridade"),
            dados.get("programa_relacionado"),
            agora,
            agora,
        ),
    )
    conexao.commit()
    return cursor.lastrowid


def empresa_ja_tem_oportunidade_aberta(conexao: sqlite3.Connection, empresa_id: int) -> bool:
    marcadores = ",".join("?" for _ in ESTAGIOS_ABERTOS)
    linha = conexao.execute(
        f"SELECT COUNT(*) FROM crm_oportunidades WHERE empresa_id = ? AND estagio IN ({marcadores})",
        (empresa_id, *ESTAGIOS_ABERTOS),
    ).fetchone()
    return linha[0] > 0


def mover_estagio(conexao: sqlite3.Connection, oportunidade_id: int, novo_estagio: str) -> None:
    if novo_estagio not in ESTAGIOS:
        raise ValueError(f"Estágio inválido: {novo_estagio!r}")
    conexao.execute(
        "UPDATE crm_oportunidades SET estagio = ?, atualizado_em = ? WHERE id = ?",
        (novo_estagio, _agora(), oportunidade_id),
    )
    conexao.commit()


def atualizar_proxima_acao(conexao: sqlite3.Connection, oportunidade_id: int, data_acao: str | None,
                            descricao: str | None, prioridade: str | None) -> None:
    conexao.execute(
        """UPDATE crm_oportunidades
           SET proxima_acao_data = ?, proxima_acao_descricao = ?, proxima_acao_prioridade = ?, atualizado_em = ?
           WHERE id = ?""",
        (data_acao, descricao, prioridade, _agora(), oportunidade_id),
    )
    conexao.commit()


def registrar_interacao(conexao: sqlite3.Connection, dados: dict) -> int:
    cursor = conexao.execute(
        """INSERT INTO crm_interacoes (oportunidade_id, tipo, data, responsavel, descricao, resultado,
           proxima_acao, criado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dados["oportunidade_id"],
            dados["tipo"],
            dados["data"],
            dados.get("responsavel"),
            dados.get("descricao"),
            dados.get("resultado"),
            dados.get("proxima_acao"),
            _agora(),
        ),
    )
    conexao.commit()
    return cursor.lastrowid


def listar_oportunidades(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexao.execute(
        """SELECT o.*, e.razao_social AS empresa_nome, e.cidade AS empresa_cidade
           FROM crm_oportunidades o LEFT JOIN empresas e ON e.id = o.empresa_id
           ORDER BY o.atualizado_em DESC"""
    ).fetchall()


def listar_interacoes(conexao: sqlite3.Connection, oportunidade_id: int) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT * FROM crm_interacoes WHERE oportunidade_id = ? ORDER BY data DESC", (oportunidade_id,)
    ).fetchall()


def listar_interacoes_recentes(conexao: sqlite3.Connection, limite: int = 5) -> list[sqlite3.Row]:
    """Últimas interações registradas em qualquer oportunidade — uma
    query só (em vez de abrir conexão por oportunidade), para a
    dashboard mostrar "atividade recente"."""
    return conexao.execute(
        """SELECT i.data, i.tipo, i.descricao, o.titulo AS oportunidade_titulo
           FROM crm_interacoes i JOIN crm_oportunidades o ON o.id = i.oportunidade_id
           ORDER BY i.data DESC, i.id DESC LIMIT ?""",
        (limite,),
    ).fetchall()


def classificar_follow_ups(oportunidades: list[dict], hoje: date | None = None) -> dict:
    """Separa oportunidades ABERTAS em: atrasadas, de hoje, futuras, e sem
    follow-up definido. Função pura — recebe uma lista de dicts (ou
    sqlite3.Row convertidos) para poder ser testada sem banco."""
    hoje = hoje or datetime.now(timezone.utc).date()
    atrasadas, hoje_lista, futuras, sem_followup = [], [], [], []

    for op in oportunidades:
        if op.get("estagio", "").startswith("Fechado"):
            continue
        data_texto = op.get("proxima_acao_data")
        if not data_texto:
            sem_followup.append(op)
            continue
        try:
            data_acao = datetime.fromisoformat(str(data_texto)[:10]).date()
        except ValueError:
            sem_followup.append(op)
            continue
        if data_acao < hoje:
            atrasadas.append(op)
        elif data_acao == hoje:
            hoje_lista.append(op)
        else:
            futuras.append(op)

    return {"atrasadas": atrasadas, "hoje": hoje_lista, "futuras": futuras, "sem_followup": sem_followup}


def valor_potencial_total(oportunidades: list[dict]) -> float:
    """Soma o valor potencial só das oportunidades ainda abertas
    (Fechado — perdido nunca conta; Fechado — ganho também não, porque
    esse valor já não é mais "potencial")."""
    return sum(
        (op.get("valor_potencial") or 0)
        for op in oportunidades
        if not op.get("estagio", "").startswith("Fechado")
    )


def oportunidades_sem_proxima_acao(oportunidades: list[dict]) -> list[dict]:
    """Oportunidades abertas que não têm nenhuma próxima ação definida —
    risco real de serem esquecidas."""
    return [
        op for op in oportunidades
        if not op.get("estagio", "").startswith("Fechado") and not op.get("proxima_acao_data")
    ]


def contar_por_estagio(oportunidades: list[dict]) -> dict:
    contagem = {estagio: 0 for estagio in ESTAGIOS}
    for op in oportunidades:
        estagio = op.get("estagio")
        if estagio in contagem:
            contagem[estagio] += 1
    return contagem
