"""Acesso e manutenção do banco SQLite do agente-tjms.

Schema, conexão e upserts. Idempotente: pode ser chamado em runs repetidos.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgao_julgador (
    cd_orgao_julgador INTEGER PRIMARY KEY,
    cd_foro           INTEGER NOT NULL,
    nome              TEXT    NOT NULL,
    monitorado        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessao (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nu_sessao         INTEGER NOT NULL,
    nu_seq_sessao     INTEGER NOT NULL,
    cd_orgao_julgador INTEGER NOT NULL REFERENCES orgao_julgador(cd_orgao_julgador),
    dt_pauta_utc      TEXT    NOT NULL,
    coletada_em       TEXT    NOT NULL,
    UNIQUE (nu_sessao, nu_seq_sessao)
);
CREATE INDEX IF NOT EXISTS idx_sessao_dtpauta ON sessao(dt_pauta_utc);

CREATE TABLE IF NOT EXISTS processo_pautado (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id           INTEGER NOT NULL REFERENCES sessao(id) ON DELETE CASCADE,
    codigo_processo     TEXT    NOT NULL,
    numero_unificado    TEXT,
    classe              TEXT,
    relator             TEXT,
    partes_json         TEXT,
    ordem_pauta         INTEGER,
    status_acordao      TEXT    NOT NULL DEFAULT 'pendente',
    coletado_em         TEXT    NOT NULL,
    atualizado_em       TEXT    NOT NULL,
    raw_json            TEXT,
    de_sit_pauta        TEXT,
    assunto             TEXT,
    decisao             TEXT,
    exibir_decisao      INTEGER NOT NULL DEFAULT 0,
    segredo_justica     INTEGER NOT NULL DEFAULT 0,
    cd_situacao_proc    TEXT,
    cd_situacao_julgam  INTEGER,
    url_consulta        TEXT,
    tentativas_rastreador INTEGER NOT NULL DEFAULT 0,
    ultimo_rastreio_em    TEXT,
    UNIQUE (sessao_id, codigo_processo)
);
CREATE INDEX IF NOT EXISTS idx_pp_status     ON processo_pautado(status_acordao);
CREATE INDEX IF NOT EXISTS idx_pp_numero_cnj ON processo_pautado(numero_unificado);

CREATE TABLE IF NOT EXISTS acordao (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_pautado_id INTEGER NOT NULL REFERENCES processo_pautado(id) ON DELETE CASCADE,
    dt_julgamento       TEXT,
    dt_publicacao_dje   TEXT,
    ementa              TEXT,
    cd_documento        INTEGER,
    url_pdf             TEXT,
    capturado_em        TEXT    NOT NULL,
    UNIQUE (processo_pautado_id)
);

CREATE TABLE IF NOT EXISTS execucao (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    modulo        TEXT NOT NULL,
    iniciado_em   TEXT NOT NULL,
    finalizado_em TEXT,
    status        TEXT NOT NULL,
    mensagem      TEXT,
    metricas_json TEXT
);
"""

# Colunas adicionadas a processo_pautado depois do schema da Sessão 2.
# Usado por _migrate() pra aplicar ALTER TABLE ADD COLUMN em DBs antigos.
# Em DB novo, essas colunas já vêm via CREATE TABLE acima.
_MIGRACOES_PP: tuple[tuple[str, str], ...] = (
    ("de_sit_pauta",       "TEXT"),
    ("assunto",            "TEXT"),
    ("decisao",            "TEXT"),
    ("exibir_decisao",     "INTEGER NOT NULL DEFAULT 0"),
    ("segredo_justica",    "INTEGER NOT NULL DEFAULT 0"),
    ("cd_situacao_proc",   "TEXT"),
    ("cd_situacao_julgam", "INTEGER"),
    ("url_consulta",       "TEXT"),
    # S4 — controle de fila do rastreador
    ("tentativas_rastreador", "INTEGER NOT NULL DEFAULT 0"),
    ("ultimo_rastreio_em",    "TEXT"),
)

# S4 — migração da tabela acordao: alinhar com retorno do parser CPOSG5.
# numero_acordao sai (não existe no HTML); dt_publicacao vira dt_publicacao_dje.
_MIGRACOES_ACORDAO_DROP:   tuple[str, ...]              = ("numero_acordao",)
_MIGRACOES_ACORDAO_ADD:    tuple[tuple[str, str], ...]  = (
    ("dt_julgamento", "TEXT"),
    ("cd_documento",  "INTEGER"),
)
_MIGRACOES_ACORDAO_RENAME: tuple[tuple[str, str], ...]  = (
    ("dt_publicacao", "dt_publicacao_dje"),
)


def get_conn(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Abre conexão SQLite com row_factory=Row e FKs habilitadas.

    Cria o diretório pai se ainda não existir. Caller é responsável por close().
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> list[str]:
    """ALTER TABLE idempotente para processo_pautado e acordao.

    Retorna lista de operações aplicadas (prefixadas por tabela). Vazia em DB já atualizado.
    """
    mudancas: list[str] = []

    # processo_pautado: ADD COLUMN
    cols_pp = {row["name"] for row in conn.execute("PRAGMA table_info(processo_pautado)")}
    for nome, tipo in _MIGRACOES_PP:
        if nome not in cols_pp:
            conn.execute(f"ALTER TABLE processo_pautado ADD COLUMN {nome} {tipo}")
            mudancas.append(f"processo_pautado.+{nome}")

    # acordao: DROP / ADD / RENAME
    cols_ac = {row["name"] for row in conn.execute("PRAGMA table_info(acordao)")}
    for nome in _MIGRACOES_ACORDAO_DROP:
        if nome in cols_ac:
            conn.execute(f"ALTER TABLE acordao DROP COLUMN {nome}")
            cols_ac.discard(nome)
            mudancas.append(f"acordao.-{nome}")
    for nome, tipo in _MIGRACOES_ACORDAO_ADD:
        if nome not in cols_ac:
            conn.execute(f"ALTER TABLE acordao ADD COLUMN {nome} {tipo}")
            cols_ac.add(nome)
            mudancas.append(f"acordao.+{nome}")
    for antigo, novo in _MIGRACOES_ACORDAO_RENAME:
        if antigo in cols_ac and novo not in cols_ac:
            conn.execute(f"ALTER TABLE acordao RENAME COLUMN {antigo} TO {novo}")
            cols_ac.discard(antigo)
            cols_ac.add(novo)
            mudancas.append(f"acordao.{antigo}->{novo}")

    if mudancas:
        conn.commit()
    return mudancas


def init_db(conn: sqlite3.Connection) -> list[str]:
    """Cria tabelas/índices (idempotente) e aplica migrações. Retorna colunas adicionadas."""
    conn.executescript(SCHEMA)
    conn.commit()
    return _migrate(conn)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def upsert_orgao(
    conn: sqlite3.Connection,
    *,
    cd_orgao_julgador: int,
    cd_foro: int,
    nome: str,
    monitorado: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO orgao_julgador (cd_orgao_julgador, cd_foro, nome, monitorado)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cd_orgao_julgador) DO UPDATE SET
            cd_foro    = excluded.cd_foro,
            nome       = excluded.nome,
            monitorado = excluded.monitorado
        """,
        (cd_orgao_julgador, cd_foro, nome, 1 if monitorado else 0),
    )


def upsert_sessao(
    conn: sqlite3.Connection,
    *,
    nu_sessao: int,
    nu_seq_sessao: int,
    cd_orgao_julgador: int,
    dt_pauta_utc: str,
) -> int:
    """Retorna o id da sessão (após insert ou no caso de já existir)."""
    row = conn.execute(
        """
        INSERT INTO sessao (nu_sessao, nu_seq_sessao, cd_orgao_julgador, dt_pauta_utc, coletada_em)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(nu_sessao, nu_seq_sessao) DO UPDATE SET
            cd_orgao_julgador = excluded.cd_orgao_julgador,
            dt_pauta_utc      = excluded.dt_pauta_utc,
            coletada_em       = excluded.coletada_em
        RETURNING id
        """,
        (nu_sessao, nu_seq_sessao, cd_orgao_julgador, dt_pauta_utc, _now_iso()),
    ).fetchone()
    return row["id"]


def upsert_processo_pautado(
    conn: sqlite3.Connection,
    *,
    sessao_id: int,
    codigo_processo: str,
    numero_unificado: str | None = None,
    classe: str | None = None,
    relator: str | None = None,
    partes_json: str | None = None,
    ordem_pauta: int | None = None,
    raw_json: str | None = None,
    de_sit_pauta: str | None = None,
    assunto: str | None = None,
    decisao: str | None = None,
    exibir_decisao: bool = False,
    segredo_justica: bool = False,
    cd_situacao_proc: str | None = None,
    cd_situacao_julgam: int | None = None,
    url_consulta: str | None = None,
) -> int:
    """Retorna o id do processo_pautado.

    Não toca em status_acordao no conflito — campo é responsabilidade do rastreador.
    coletado_em é gravado só no primeiro insert; atualizado_em sempre.
    """
    now = _now_iso()
    row = conn.execute(
        """
        INSERT INTO processo_pautado (
            sessao_id, codigo_processo, numero_unificado, classe, relator,
            partes_json, ordem_pauta, coletado_em, atualizado_em, raw_json,
            de_sit_pauta, assunto, decisao, exibir_decisao, segredo_justica,
            cd_situacao_proc, cd_situacao_julgam, url_consulta
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sessao_id, codigo_processo) DO UPDATE SET
            numero_unificado    = excluded.numero_unificado,
            classe              = excluded.classe,
            relator             = excluded.relator,
            partes_json         = excluded.partes_json,
            ordem_pauta         = excluded.ordem_pauta,
            atualizado_em       = excluded.atualizado_em,
            raw_json            = excluded.raw_json,
            de_sit_pauta        = excluded.de_sit_pauta,
            assunto             = excluded.assunto,
            decisao             = excluded.decisao,
            exibir_decisao      = excluded.exibir_decisao,
            segredo_justica     = excluded.segredo_justica,
            cd_situacao_proc    = excluded.cd_situacao_proc,
            cd_situacao_julgam  = excluded.cd_situacao_julgam,
            url_consulta        = excluded.url_consulta
        RETURNING id
        """,
        (
            sessao_id, codigo_processo, numero_unificado, classe, relator,
            partes_json, ordem_pauta, now, now, raw_json,
            de_sit_pauta, assunto, decisao,
            1 if exibir_decisao else 0,
            1 if segredo_justica else 0,
            cd_situacao_proc, cd_situacao_julgam, url_consulta,
        ),
    ).fetchone()
    return row["id"]


def log_execucao_inicio(conn: sqlite3.Connection, modulo: str) -> int:
    """Grava o início de uma execução; commita imediatamente. Retorna o id."""
    row = conn.execute(
        """
        INSERT INTO execucao (modulo, iniciado_em, status)
        VALUES (?, ?, 'em_andamento')
        RETURNING id
        """,
        (modulo, _now_iso()),
    ).fetchone()
    conn.commit()
    return row["id"]


def log_execucao_fim(
    conn: sqlite3.Connection,
    execucao_id: int,
    *,
    status: str,
    mensagem: str | None = None,
    metricas: dict[str, Any] | None = None,
) -> None:
    """Finaliza a execução. status: 'ok'|'erro'|'parcial'. Commita imediatamente."""
    conn.execute(
        """
        UPDATE execucao
           SET finalizado_em = ?,
               status        = ?,
               mensagem      = ?,
               metricas_json = ?
         WHERE id = ?
        """,
        (
            _now_iso(),
            status,
            mensagem,
            json.dumps(metricas, ensure_ascii=False) if metricas is not None else None,
            execucao_id,
        ),
    )
    conn.commit()
