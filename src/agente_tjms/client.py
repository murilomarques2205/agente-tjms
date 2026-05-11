"""Cliente HTTP para a API de pauta de julgamento do TJMS (pública)."""

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

API_BASE = "/pauta-julgamento/api/1.0"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) agente-tjms/0.1",
    "Accept": "application/json, text/plain, */*",
}

_RETRY_EXC = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.HTTPError,
)


class TJMSClient:
    """Cliente para a API de pauta de julgamento do TJMS.

    Todos os endpoints usados são públicos. Mantém uma única requests.Session
    (cookies/keep-alive). Use como context manager para fechar a Session.
    """

    def __init__(self, base_url: str = BASE_URL, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

    @retry(
        retry=retry_if_exception_type(_RETRY_EXC),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, params=params, timeout=self.timeout)
        if 500 <= resp.status_code < 600:
            raise requests.exceptions.HTTPError(
                f"{resp.status_code} server error at {url}", response=resp
            )
        return resp

    def get_orgaos_julgadores(self) -> tuple[list[dict[str, Any]], str]:
        """Lista todos os órgãos. Público."""
        resp = self._get(f"{API_BASE}/consulta/orgaos-julgadores")
        resp.raise_for_status()
        return resp.json(), resp.text

    def get_sessoes_agendadas(
        self, *, cd_foro: int, cd_orgao_julgador: int
    ) -> tuple[list[dict[str, Any]], str]:
        """Lista sessões agendadas de um órgão. Público."""
        resp = self._get(
            f"{API_BASE}/sessao-agendada",
            params={"cdForo": cd_foro, "cdOrgaoJulgador": cd_orgao_julgador},
        )
        resp.raise_for_status()
        return resp.json(), resp.text

    def get_processo_em_pauta(
        self,
        *,
        cd_orgao_julgador: int,
        nu_sessao: int,
        nu_seq_sessao: int,
        pagina: int = 0,
        tamanho_pagina: int = 0,
    ) -> tuple[dict[str, Any], str]:
        """Processos pautados em uma sessão. Público.

        Com tamanho_pagina=0 (default), a API retorna todos os processos da
        sessão em uma única resposta e preenche paginacao.total.
        """
        resp = self._get(
            f"{API_BASE}/processo-em-pauta",
            params={
                "cdOrgaoJulgador": cd_orgao_julgador,
                "nuSessao": nu_sessao,
                "nuSeqSessao": nu_seq_sessao,
                "paginacao.tamanhoPagina": tamanho_pagina,
                "paginacao.paginaAtual": pagina,
            },
        )
        resp.raise_for_status()
        return resp.json(), resp.text

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> TJMSClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
