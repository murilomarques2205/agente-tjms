"""Configurações estáticas do agente-tjms.

Valores podem ser sobrescritos via .env (carregado automaticamente no import).
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # no-op se .env não existir

# --- caminhos ---
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
DB_PATH: Path = DATA_DIR / "tjms.sqlite"
RELATORIOS_DIR: Path = DATA_DIR / "relatorios"

# --- API TJMS ---
BASE_URL: str = os.environ.get("BASE_URL", "https://esaj.tjms.jus.br")

# Timezone do tribunal — converte dtPauta (UTC) para hora local nos relatórios.
# Fail-fast: ZoneInfo levanta ZoneInfoNotFoundError se TZ for inválida.
TZ_TRIBUNAL: ZoneInfo = ZoneInfo(os.environ.get("TZ", "America/Campo_Grande"))

# --- órgãos monitorados ---
# Snapshot fixo dos 6 órgãos criminais alvo, confirmados no discovery (Sessão 1).
# Estrutura idêntica à da resposta do endpoint /consulta/orgaos-julgadores.
ORGAOS_MONITORADOS: tuple[dict[str, int | str], ...] = (
    {"cdForo": 900, "cdOrgaoJulgador": 8,
     "nmOrgaoJulgador": "1ª Câmara Criminal - Tribunal de Justiça"},
    {"cdForo": 900, "cdOrgaoJulgador": 9,
     "nmOrgaoJulgador": "2ª Câmara Criminal - Tribunal de Justiça"},
    {"cdForo": 900, "cdOrgaoJulgador": 49,
     "nmOrgaoJulgador": "3ª Câmara Criminal - Tribunal de Justiça"},
    {"cdForo": 900, "cdOrgaoJulgador": 53,
     "nmOrgaoJulgador": "1ª Seção Criminal - Tribunal de Justiça"},
    {"cdForo": 900, "cdOrgaoJulgador": 51,
     "nmOrgaoJulgador": "2ª Seção Criminal - Tribunal de Justiça"},
    {"cdForo": 900, "cdOrgaoJulgador": 52,
     "nmOrgaoJulgador": "Seção Especial - Criminal - Tribunal de Justiça"},
)
