"""Repositório de documentos da OSC (Cérebro da OSC -> Documentos).

Fluxo: upload -> arquivo original preservado em dados/documentos_osc/ ->
extração de texto (PDF, DOCX, TXT, XLSX/XLS) -> texto guardado no banco
-> busca por conteúdo. Nada é interpretado por IA: o que o sistema mostra
é sempre um trecho LITERAL do documento, com o nome do arquivo como fonte.
Se o texto não pôde ser extraído (PDF escaneado, arquivo protegido), o
status diz isso — nunca finge que leu.

Tabela `osc_documentos` (já existia só com metadados) ganha colunas novas
por migração idempotente; documentos antigos, sem arquivo, continuam
existindo como "registro sem arquivo"."""
from __future__ import annotations

import hashlib
import io
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

CATEGORIAS = [
    "Estatuto", "CNPJ/Cadastro", "Certificado", "Apresentação institucional", "Projeto",
    "Plano de trabalho", "Relatório", "Relatório de impacto", "Portfólio", "Atuação territorial",
    "Lei/Regulamento", "Outro",
]
EXTENSOES_SUPORTADAS = {".pdf", ".docx", ".txt", ".xlsx", ".xls"}

STATUS_PROCESSADO = "PROCESSADO"
STATUS_SEM_TEXTO = "SEM_TEXTO_EXTRAIDO"
STATUS_ERRO = "ERRO"
STATUS_NAO_SUPORTADO = "FORMATO_NAO_SUPORTADO"

ROTULOS_STATUS = {
    STATUS_PROCESSADO: "Texto extraído",
    STATUS_SEM_TEXTO: "Sem texto extraível (ex: PDF escaneado)",
    STATUS_ERRO: "Erro ao processar",
    STATUS_NAO_SUPORTADO: "Formato não suportado — arquivo guardado, sem leitura",
}

TAMANHO_MAXIMO_BYTES = 25 * 1024 * 1024


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


_COLUNAS_NOVAS = {
    "nome_arquivo": "TEXT",
    "extensao": "TEXT",
    "tamanho_bytes": "INTEGER",
    "categoria": "TEXT",
    "caminho_arquivo": "TEXT",
    "sha256": "TEXT",
    "status_processamento": "TEXT",
    "detalhe_processamento": "TEXT",
    "texto_extraido": "TEXT",
    "paginas": "INTEGER",
    "enviado_em": "TEXT",
}


def migrar(conexao: sqlite3.Connection) -> None:
    """Idempotente: acrescenta as colunas de arquivo/texto em bancos antigos."""
    atuais = {l["name"] for l in conexao.execute("PRAGMA table_info(osc_documentos)")}
    if not atuais:
        return  # tabela ainda não existe (osc.criar_tabelas cria antes)
    for coluna, definicao in _COLUNAS_NOVAS.items():
        if coluna not in atuais:
            conexao.execute(f"ALTER TABLE osc_documentos ADD COLUMN {coluna} {definicao}")
    conexao.commit()


def _nome_seguro(nome: str) -> str:
    base = Path(nome).name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "documento"


# ---------------------------------------------------------------- extração
def extrair_texto(conteudo: bytes, extensao: str) -> tuple[str, int | None]:
    """Devolve (texto, nº de páginas/abas). Texto vazio = nada extraível.
    Levanta exceção se o arquivo estiver corrompido (quem chama registra ERRO)."""
    ext = extensao.lower()
    if ext == ".txt":
        for codificacao in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return conteudo.decode(codificacao), None
            except UnicodeDecodeError:
                continue
        return "", None
    if ext == ".pdf":
        from pypdf import PdfReader

        leitor = PdfReader(io.BytesIO(conteudo))
        partes = [(pagina.extract_text() or "") for pagina in leitor.pages]
        return "\n\n".join(p.strip() for p in partes if p.strip()), len(leitor.pages)
    if ext == ".docx":
        import docx

        documento = docx.Document(io.BytesIO(conteudo))
        blocos = [p.text for p in documento.paragraphs if p.text.strip()]
        for tabela in documento.tables:
            for linha in tabela.rows:
                celulas = [c.text.strip() for c in linha.cells if c.text.strip()]
                if celulas:
                    blocos.append(" | ".join(celulas))
        return "\n".join(blocos), None
    if ext == ".xlsx":
        import openpyxl

        pasta = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
        blocos = []
        for aba in pasta.worksheets:
            blocos.append(f"[Aba: {aba.title}]")
            for linha in aba.iter_rows(values_only=True):
                valores = [str(v).strip() for v in linha if v is not None and str(v).strip()]
                if valores:
                    blocos.append(" | ".join(valores))
        return "\n".join(blocos), len(pasta.worksheets)
    if ext == ".xls":
        import xlrd

        pasta = xlrd.open_workbook(file_contents=conteudo)
        blocos = []
        for aba in pasta.sheets():
            blocos.append(f"[Aba: {aba.name}]")
            for i in range(aba.nrows):
                valores = [str(v).strip() for v in aba.row_values(i) if str(v).strip()]
                if valores:
                    blocos.append(" | ".join(valores))
        return "\n".join(blocos), pasta.nsheets
    raise ValueError(f"Formato não suportado: {extensao}")


# ---------------------------------------------------------------- CRUD
def adicionar(conexao: sqlite3.Connection, osc_id: int, nome_arquivo: str, conteudo: bytes,
              pasta_destino: Path, categoria: str = "Outro", descricao: str | None = None) -> dict:
    """Guarda o arquivo ORIGINAL, extrai o texto e registra tudo. Mesmo
    arquivo (mesmo conteúdo) enviado duas vezes na mesma OSC não duplica:
    devolve o registro existente com `duplicado=True`."""
    migrar(conexao)
    if len(conteudo) > TAMANHO_MAXIMO_BYTES:
        raise ValueError(f"Arquivo maior que o limite de {TAMANHO_MAXIMO_BYTES // (1024 * 1024)} MB.")
    if not conteudo:
        raise ValueError("Arquivo vazio.")

    sha = hashlib.sha256(conteudo).hexdigest()
    existente = conexao.execute(
        "SELECT id FROM osc_documentos WHERE osc_id = ? AND sha256 = ?", (osc_id, sha)
    ).fetchone()
    if existente:
        return {"id": existente["id"], "duplicado": True, "status": None}

    extensao = Path(nome_arquivo).suffix.lower()
    pasta_destino.mkdir(parents=True, exist_ok=True)
    caminho = pasta_destino / f"{sha[:12]}_{_nome_seguro(nome_arquivo)}"
    caminho.write_bytes(conteudo)  # original preservado, nunca modificado

    texto, paginas, detalhe = "", None, None
    if extensao not in EXTENSOES_SUPORTADAS:
        status = STATUS_NAO_SUPORTADO
    else:
        try:
            texto, paginas = extrair_texto(conteudo, extensao)
            status = STATUS_PROCESSADO if texto.strip() else STATUS_SEM_TEXTO
        except Exception as exc:  # arquivo corrompido/protegido — registra, não derruba o upload
            status, detalhe = STATUS_ERRO, f"{type(exc).__name__}: {exc}"[:300]

    agora = _agora()
    cursor = conexao.execute(
        """INSERT INTO osc_documentos
           (osc_id, tipo, nome, descricao, referencia, origem, criado_em, nome_arquivo, extensao, tamanho_bytes,
            categoria, caminho_arquivo, sha256, status_processamento, detalhe_processamento, texto_extraido,
            paginas, enviado_em)
           VALUES (?, ?, ?, ?, ?, 'MANUAL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (osc_id, categoria, nome_arquivo, descricao, str(caminho), agora, nome_arquivo, extensao, len(conteudo),
         categoria, str(caminho), sha, status, detalhe, texto or None, paginas, agora),
    )
    conexao.commit()
    return {"id": cursor.lastrowid, "duplicado": False, "status": status, "caracteres": len(texto)}


def listar(conexao: sqlite3.Connection, osc_id: int) -> list[dict]:
    migrar(conexao)
    return [dict(l) for l in conexao.execute(
        """SELECT id, nome, nome_arquivo, extensao, tamanho_bytes, categoria, descricao, caminho_arquivo,
                  status_processamento, detalhe_processamento, paginas, enviado_em, criado_em, referencia,
                  LENGTH(texto_extraido) AS caracteres
           FROM osc_documentos WHERE osc_id = ? ORDER BY COALESCE(enviado_em, criado_em) DESC""",
        (osc_id,),
    ).fetchall()]


def obter_texto(conexao: sqlite3.Connection, documento_id: int) -> str | None:
    linha = conexao.execute("SELECT texto_extraido FROM osc_documentos WHERE id = ?", (documento_id,)).fetchone()
    return linha["texto_extraido"] if linha else None


def excluir(conexao: sqlite3.Connection, documento_id: int, apagar_arquivo: bool = True) -> bool:
    """Exclui o registro (e o arquivo guardado). Ação explícita do usuário."""
    linha = conexao.execute("SELECT caminho_arquivo FROM osc_documentos WHERE id = ?", (documento_id,)).fetchone()
    if linha is None:
        return False
    conexao.execute("DELETE FROM osc_documentos WHERE id = ?", (documento_id,))
    conexao.commit()
    if apagar_arquivo and linha["caminho_arquivo"]:
        caminho = Path(linha["caminho_arquivo"])
        if caminho.exists():
            caminho.unlink()
    return True


# ---------------------------------------------------------------- busca
def _normalizar(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return sem_acento


def buscar(conexao: sqlite3.Connection, osc_id: int, termo: str, tamanho_trecho: int = 220,
           max_trechos_por_documento: int = 3) -> list[dict]:
    """Busca literal (ignora acento/caixa) no texto extraído. Devolve
    trechos REAIS com o documento de origem — o "Fonte: documento X" que a
    regra de ouro exige. Termo vazio devolve []."""
    termo = termo.strip()
    if not termo:
        return []
    migrar(conexao)
    alvo = _normalizar(termo)
    resultados = []
    for linha in conexao.execute(
        "SELECT id, nome_arquivo, categoria, texto_extraido FROM osc_documentos WHERE osc_id = ? AND texto_extraido IS NOT NULL",
        (osc_id,),
    ).fetchall():
        original = linha["texto_extraido"]
        normalizado = _normalizar(original)
        # Se a normalização mudou o comprimento (caracteres compostos raros), as posições não
        # batem com o original: nesse caso o trecho sai do texto normalizado (sem acento), mas continua literal.
        texto = original if len(normalizado) == len(original) else normalizado
        trechos, inicio = [], 0
        while len(trechos) < max_trechos_por_documento:
            posicao = normalizado.find(alvo, inicio)
            if posicao < 0:
                break
            ini = max(0, posicao - tamanho_trecho // 2)
            fim = min(len(texto), posicao + len(alvo) + tamanho_trecho // 2)
            trechos.append(texto[ini:fim].replace("\n", " ").strip())
            inicio = posicao + len(alvo)
        if trechos:
            total = normalizado.count(alvo)
            resultados.append({"documento_id": linha["id"], "documento": linha["nome_arquivo"],
                               "categoria": linha["categoria"], "ocorrencias": total, "trechos": trechos})
    return sorted(resultados, key=lambda r: -r["ocorrencias"])


def textos_para_contexto(conexao: sqlite3.Connection, osc_id: int) -> list[dict]:
    """Interface para módulos futuros consultarem o conhecimento da OSC:
    lista {documento, categoria, texto} só dos documentos com texto extraído."""
    migrar(conexao)
    return [{"documento": l["nome_arquivo"], "categoria": l["categoria"], "texto": l["texto_extraido"]}
            for l in conexao.execute(
                "SELECT nome_arquivo, categoria, texto_extraido FROM osc_documentos WHERE osc_id = ? AND texto_extraido IS NOT NULL",
                (osc_id,)).fetchall()]
