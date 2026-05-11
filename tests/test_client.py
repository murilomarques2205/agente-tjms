"""Testes do TJMSClient — sem dependência de rede."""

from __future__ import annotations

import json

import pytest
import responses

from agente_tjms.client import API_BASE, PAUTA_JULGAMENTO_PATH, TJMSClient
from agente_tjms.config import BASE_URL, PROJECT_ROOT

FIXTURE_ORGAOS = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "orgaos.json").read_text(encoding="utf-8")
)


@responses.activate
def test_get_orgaos_julgadores_retorna_lista_e_raw_text():
    responses.add(
        responses.GET,
        f"{BASE_URL}{API_BASE}/consulta/orgaos-julgadores",
        json=FIXTURE_ORGAOS,
        status=200,
    )
    with TJMSClient() as client:
        orgaos, raw = client.get_orgaos_julgadores()

    assert isinstance(orgaos, list)
    assert len(orgaos) == 29
    # Os 6 cdOrgaoJulgador alvo devem aparecer na lista.
    assert {o["cdOrgaoJulgador"] for o in orgaos} >= {8, 9, 49, 51, 52, 53}
    # raw_text é o corpo cru — deve poder ser reparseado e bater com o JSON parseado.
    assert json.loads(raw) == FIXTURE_ORGAOS


@responses.activate
def test_get_processos_em_pauta_dispara_bootstrap_implicito():
    responses.add(
        responses.GET,
        f"{BASE_URL}{PAUTA_JULGAMENTO_PATH}/consulta",
        body="<html>...</html>",
        status=200,
        headers={"Set-Cookie": "JSESSIONID=abc123; path=/pauta-julgamento"},
    )
    responses.add(
        responses.GET,
        f"{BASE_URL}{API_BASE}/processos-em-pauta/",
        json={"lista": [{"codigoProcesso": "X"}]},
        status=200,
    )

    with TJMSClient() as client:
        assert client._sessao_estabelecida is False
        data, _raw = client.get_processos_em_pauta(
            cd_orgao_julgador=8, nu_sessao=1546, nu_seq_sessao=20523
        )
        assert client._sessao_estabelecida is True

    assert data == {"lista": [{"codigoProcesso": "X"}]}
    assert len(responses.calls) == 2
    assert "/pauta-julgamento/consulta" in responses.calls[0].request.url
    assert "/processos-em-pauta/" in responses.calls[1].request.url


@responses.activate
def test_bootstrap_falha_se_sem_jsessionid():
    # 200 OK mas sem Set-Cookie -> nenhum JSESSIONID na Session.cookies
    responses.add(
        responses.GET,
        f"{BASE_URL}{PAUTA_JULGAMENTO_PATH}/consulta",
        body="<html>manutenção</html>",
        status=200,
    )

    with TJMSClient() as client:
        with pytest.raises(RuntimeError, match="JSESSIONID"):
            client.bootstrap_sessao()
        assert client._sessao_estabelecida is False


@responses.activate
def test_processos_em_pauta_falha_se_redireciona_para_cas():
    # Bootstrap OK
    responses.add(
        responses.GET,
        f"{BASE_URL}{PAUTA_JULGAMENTO_PATH}/consulta",
        body="ok",
        status=200,
        headers={"Set-Cookie": "JSESSIONID=abc; path=/pauta-julgamento"},
    )
    # Endpoint protegido ainda redireciona para CAS (cookie inválido/expirado simulado)
    responses.add(
        responses.GET,
        f"{BASE_URL}{API_BASE}/processos-em-pauta/",
        status=302,
        headers={"Location": f"{BASE_URL}/sajcas/login?service=..."},
    )

    with TJMSClient() as client:
        with pytest.raises(RuntimeError, match="CAS"):
            client.get_processos_em_pauta(
                cd_orgao_julgador=8, nu_sessao=1, nu_seq_sessao=1
            )
