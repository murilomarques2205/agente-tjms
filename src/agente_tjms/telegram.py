"""Envio de mensagens e documentos via Bot API do Telegram.

As credenciais (AGENTE_TJMS_TG_TOKEN, AGENTE_TJMS_TG_CHAT_ID) vêm do
ambiente — em produção, injetadas pelo EnvironmentFile do systemd.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

API_BASE = "https://api.telegram.org"


class TelegramError(RuntimeError):
    """Falha ao falar com a Bot API do Telegram."""


def ler_credenciais() -> tuple[str, str] | None:
    """Retorna (token, chat_id) do ambiente, ou None se algum estiver ausente."""
    token = os.environ.get("AGENTE_TJMS_TG_TOKEN", "").strip()
    chat_id = os.environ.get("AGENTE_TJMS_TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


def _checar_resposta(resp: requests.Response, acao: str) -> None:
    try:
        corpo = resp.json()
    except ValueError:
        raise TelegramError(
            f"{acao}: resposta não-JSON (HTTP {resp.status_code})"
        ) from None
    if not corpo.get("ok"):
        raise TelegramError(f"{acao}: {corpo.get('description', 'erro desconhecido')}")


def _post(url: str, acao: str, *, timeout: float, **kwargs) -> None:
    """POST + checagem; falha de rede ou resposta inválida vira TelegramError."""
    try:
        resp = requests.post(url, timeout=timeout, **kwargs)
    except requests.exceptions.RequestException as e:
        raise TelegramError(f"{acao}: falha de rede — {e}") from e
    _checar_resposta(resp, acao)


def enviar_mensagem(token: str, chat_id: str, texto: str, *, timeout: float = 15) -> None:
    """Envia uma mensagem de texto. Levanta TelegramError em caso de falha."""
    _post(
        f"{API_BASE}/bot{token}/sendMessage",
        "sendMessage",
        timeout=timeout,
        data={"chat_id": chat_id, "text": texto},
    )


def enviar_documento(
    token: str,
    chat_id: str,
    caminho: Path,
    *,
    legenda: str | None = None,
    timeout: float = 60,
) -> None:
    """Envia um arquivo como documento. Levanta TelegramError em caso de falha."""
    caminho = Path(caminho)
    data = {"chat_id": chat_id}
    if legenda:
        data["caption"] = legenda
    with caminho.open("rb") as f:
        _post(
            f"{API_BASE}/bot{token}/sendDocument",
            "sendDocument",
            timeout=timeout,
            data=data,
            files={"document": (caminho.name, f)},
        )
