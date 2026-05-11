"""Inicializa o banco do agente-tjms.

Cria tabelas e popula orgao_julgador a partir do fixture tests/fixtures/orgaos.json
(snapshot real coletado no discovery), marcando monitorado=1 nos 6 órgãos criminais alvo.

Idempotente: pode rodar várias vezes sem efeito colateral.
"""

from __future__ import annotations

import json
import sys

from agente_tjms.config import DB_PATH, ORGAOS_MONITORADOS, PROJECT_ROOT
from agente_tjms.db import get_conn, init_db, upsert_orgao

FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "orgaos.json"


def main() -> int:
    if not FIXTURE_PATH.exists():
        print(f"ERRO: fixture não encontrada em {FIXTURE_PATH}", file=sys.stderr)
        return 1

    with FIXTURE_PATH.open(encoding="utf-8") as f:
        orgaos = json.load(f)

    cds_monitorados = {o["cdOrgaoJulgador"] for o in ORGAOS_MONITORADOS}

    conn = get_conn()
    try:
        init_db(conn)
        with conn:  # transação única
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
    print(f"fixture:  {FIXTURE_PATH}")
    print(f"órgãos populados: {total}  (monitorados: {marcados}/{len(ORGAOS_MONITORADOS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
