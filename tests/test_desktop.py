"""Desktop authentication: bearer-only bootstrap, shared MCP identity, no credential in browser responses."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import auth
import config
import login
import server

TOKEN = 'private-desktop-test-token'


@pytest.fixture
def client(server_env: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv('OPENARTIFACT_DESKTOP_TOKEN', TOKEN)
    monkeypatch.setenv('OPENARTIFACT_DESKTOP_ID', 'test-instance')
    with TestClient(server.app) as opened:
        yield opened


def test_desktop_bootstrap_requires_credential(client: TestClient):
    assert client.get('/health/').json() == {'status': 'ok', 'desktop_id': 'test-instance'}
    assert client.post('/login/dev', data={}).status_code == 404
    assert client.get('/login/desktop').status_code in (404, 405)
    assert client.post('/login/desktop').status_code == 401
    assert client.post('/login/desktop', headers={'authorization': 'Bearer wrong'}).status_code == 401
    assert (
        client.post(
            '/login/desktop', headers={'authorization': f'Bearer {TOKEN}', 'origin': 'https://evil.test'}
        ).status_code
        == 403
    )
    response = client.post('/login/desktop', headers={'authorization': f'Bearer {TOKEN}'})
    assert response.status_code == 204
    assert response.headers['cache-control'] == 'no-store'
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie
    assert TOKEN not in cookie and not response.content
    assert login.read_session(client.cookies.get(login.SESSION_COOKIE))
    assert client.get('/api/me').json()['viewer'] == {
        'name': auth.DESKTOP_CLAIMS['name'],
        'email': auth.DESKTOP_CLAIMS['email'],
        'picture': None,
    }
    settings = client.get('/api/configure')
    assert TOKEN not in settings.text
    assert settings.json()['mcp'] == {
        'url': f'{config.base_url()}/mcp/',
        'auth': 'token',
        'token': None,
        'desktop': True,
    }


def test_desktop_bootstrap_disabled_without_desktop_or_with_google(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    headers = {'authorization': f'Bearer {TOKEN}'}
    monkeypatch.delenv('OPENARTIFACT_DESKTOP_TOKEN')
    assert client.post('/login/desktop', headers=headers).status_code == 404
    monkeypatch.setenv('OPENARTIFACT_DESKTOP_TOKEN', TOKEN)
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'google-client')
    assert client.post('/login/desktop', headers=headers).status_code == 404


@pytest.mark.anyio
async def test_desktop_mcp_uses_local_identity(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('OPENARTIFACT_DESKTOP_TOKEN', TOKEN)
    monkeypatch.delenv('GOOGLE_CLIENT_ID', raising=False)
    verifier = auth.make_auth_provider()
    token = await verifier.verify_token(TOKEN)
    assert token and token.claims['sub'] == auth.DESKTOP_CLAIMS['sub']
    assert await verifier.verify_token('wrong') is None
    assert await verifier.verify_token('test-dev-token') is None
    monkeypatch.delenv('OPENARTIFACT_SECRET_KEY', raising=False)
    assert config.secret_key() == TOKEN.encode()
