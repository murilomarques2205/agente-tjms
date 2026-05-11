"""CLI principal do agente-tjms.

Subcomandos:
  init-db   Inicializa schema e popula orgao_julgador a partir do fixture.
  coletar   Coleta sessões/processos dos órgãos monitorados.

Invocação: `python -m agente_tjms <subcomando>` ou `agente-tjms <subcomando>`.

A lógica de `init-db` está inline aqui em cmd_init_db; scripts/init_db.py
continua existindo como entrypoint standalone equivalente.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import coletor_pauta
from .config import DB_PATH, ORGAOS_MONITORADOS, PROJECT_ROOT
from .db import get_conn, init_db, upsert_orgao

FIXTURE_ORGAOS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "orgaos.json"


def cmd_init_db(argv: list[str] | None = None) -> int:
    """Cria tabelas e popula orgao_julgador a partir do fixture."""
    argparse.ArgumentParser(prog="agente-tjms init-db").parse_args(argv or [])

    if not FIXTURE_ORGAOS_PATH.exists():
        print(f"ERRO: fixture não encontrada em {FIXTURE_ORGAOS_PATH}", file=sys.stderr)
        return 1

    orgaos = json.loads(FIXTURE_ORGAOS_PATH.read_text(encoding="utf-8"))
    cds_monitorados = {o["cdOrgaoJulgador"] for o in ORGAOS_MONITORADOS}

    conn = get_conn()
    try:
        init_db(conn)
        with conn:
            for o in orgaos:
                upsert_orgao(
                    conn,
                    cd_orgao_julgador=o["cdOrgaoJulgador"],
                    cd_foro=o["cdForo"],
                    nome=o["nmOrgaoJulgador"],
                    monitorado=o["cdOrgaoJulgador"] in cds_monitorados,
                )
        total = conn.execute("SELECT COUNT(*) FROM orgao_julgador").fetchone()[0]
        marcados = conn.execute(
            "SELECT COUNT(*) FROM orgao_julgador WHERE monitorado = 1"
        ).fetchone()[0]
    finally:
        conn.close()

    print(f"banco:    {DB_PATH}")
    print(f"fixture:  {FIXTURE_ORGAOS_PATH}")
    print(f"órgãos populados: {total}  (monitorados: {marcados}/{len(ORGAOS_MONITORADOS)})")
    return 0


def _print_help() -> None:
    print("uso: agente-tjms <subcomando> [opções...]")
    print()
    print("subcomandos:")
    print("  init-db   Cria schema do SQLite e popula orgao_julgador.")
    print("  coletar   Coleta sessões/processos dos órgãos monitorados.")
    print()
    print("Para opções de cada subcomando: agente-tjms <subcomando> --help")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        _print_help()
        return 2
    if argv[0] in ("-h", "--help"):
        _print_help()
        return 0

    sub, *rest = argv
    if sub == "init-db":
        return cmd_init_db(rest)
    if sub == "coletar":
        return coletor_pauta.main(rest)
    print(f"subcomando desconhecido: {sub}", file=sys.stderr)
    _print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
