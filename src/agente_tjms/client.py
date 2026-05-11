"""Cliente HTTP para a API de pauta de julgamento do TJMS.

Endpoints públicos: /consulta/orgaos-julgadores, /sessao-agendada.
Endpoint protegido (requer JSESSIONID): /processos-em-pauta.

Bootstrap: GET em /pauta-julgamento/consulta?servico=526100 estabelece o cookie.
"""

from __future__ import annotations

from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import BASE_URL

# --- constantes de protocolo ---
SERVICO_ID = 526100
PAGINACAO_TAMANHO = 200
PAUTA_JULGAMENTO_PATH = "/pauta-julgamento"
API_BASE = f"{PAUTA_JULGAMENTO_PATH}/api/1.0"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) agente-tjms/0.1",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}{PAUTA_JULGAMENTO_PATH}/consulta?servico={SERVICO_ID}",
}

# Exceções transitórias que disparam retry.
# HTTPError aqui só é lançado por _get em status 5xx; 4xx volta como Response sem retry.
_RETRY_EXC = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.HTTPError,
)


class TJMSClient:
    """Cliente para a API de pauta de julgamento do TJMS.

    Mantém uma única `requests.Session` (cookies/keep-alive).
    Pode ser usado como context manager para fechar a Session automaticamente.
    """

    def __init__(self, base_url: str = BASE_URL, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        self._sessao_estabelecida = False

    # ---------- baixo nível ----------

    @retry(
        retry=retry_if_exception_type(_RETRY_EXC),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        allow_redirects: bool = False,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = self._session.get(
            url, params=params, timeout=self.timeout, allow_redirects=allow_redirects
        )
        # 5xx merece retry: convertemos em HTTPError para acionar tenacity.
        if 500 <= resp.status_code < 600:
            raise requests.exceptions.HTTPError(
                f"{resp.status_code} server error at {url}", response=resp
            )
        return resp

    # ---------- bootstrap ----------

    def bootstrap_sessao(self) -> None:
        """Estabelece o JSESSIONID via GET na página da consulta.

        Necessário antes de get_processos_em_pauta (sem cookie → 302 /sajcas/login).
        """
        resp = self._get(
            f"{PAUTA_JULGAMENTO_PATH}/consulta",
            params={"servico": SERVICO_ID},
            allow_redirects=True,
        )
        resp.raise_for_status()
        if "JSESSIONID" not in self._session.cookies:
            raise RuntimeError("bootstrap retornou 200 mas sem JSESSIONID nos cookies")
        self._sessao_estabelecida = True

    # ---------- públicos ----------

    def get_orgaos_julgadores(self) -> tuple[list[dict[str, Any]], str]:
        """Lista todos os órgãos. Endpoint público (não exige bootstrap)."""
        resp = self._get(f"{API_BASE}/consulta/orgaos-julgadores")
        resp.raise_for_status()
        return resp.json(), resp.text

    def get_sessoes_agendadas(
        self, *, cd_foro: int, cd_orgao_julgador: int
    ) -> tuple[list[dict[str, Any]], str]:
        """Lista sessões agendadas de um órgão. Endpoint público."""
        resp = self._get(
            f"{API_BASE}/sessao-agendada",
            params={"cdForo": cd_foro, "cdOrgaoJulgador": cd_orgao_julgador},
        )
        resp.raise_for_status()
        return resp.json(), resp.text

    def get_processos_em_pauta(
        self,
        *,
        cd_orgao_julgador: int,
        nu_sessao: int,
        nu_seq_sessao: int,
        pagina: int = 0,
        tamanho_pagina: int = PAGINACAO_TAMANHO,
    ) -> tuple[Any, str]:
        """Processos pautados em uma sessão. PROTEGIDO — bootstrap implícito."""
        if not self._sessao_estabelecida:
            self.bootstrap_sessao()
        resp = self._get(
            f"{API_BASE}/processos-em-pauta/",
            params={
                "cdOrgaoJulgador": cd_orgao_julgador,
                "nuSessao": nu_sessao,
                "nuSeqSessao": nu_seq_sessao,
                "paginacao.tamanhoPagina": tamanho_pagina,
                "paginacao.paginaAtual": pagina,
            },
        )
        # Mesmo após bootstrap caiu em CAS? Falhar audível em vez de devolver lixo.
        if resp.status_code in (301, 302) and "sajcas" in resp.headers.get("Location", ""):
            raise RuntimeError(
                "processos-em-pauta exigiu CAS mesmo após bootstrap; sessão não estabelecida."
            )
        resp.raise_for_status()
        return resp.json(), resp.text

    # ---------- ciclo de vida ----------

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> TJMSClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
