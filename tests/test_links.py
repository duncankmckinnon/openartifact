"""Reference facts and actual SSRF/status behavior using controlled transport."""

from __future__ import annotations

from typing import Any

import httpx2
import links
import pytest
from pydantic_ai import _ssrf

pytestmark = pytest.mark.anyio


def test_page_facts():
    facts = links.page_facts(
        'https://harbor.example/',
        '<title>Harbor</title><link rel="icon" href="/favicon.svg"><img src="/logo.svg" alt="logo">',
        [
            (
                'style',
                ':root{--brand:#0e2238}body{font-family:"Söhne",sans-serif;color:#1b1f24}h1{color:rgb(14,34,56)}@font-face{font-family:"Söhne";src:url(s.woff2)}',
            )
        ],
    )
    for expected in (
        'title: Harbor',
        '--brand: #0e2238',
        '@font-face: Söhne',
        '#0e2238 (2)',
        'https://harbor.example/logo.svg',
        'https://harbor.example/favicon.svg',
    ):
        assert expected in facts


@pytest.mark.parametrize('status', [401, 403])
async def test_non_200_is_reported(monkeypatch: pytest.MonkeyPatch, status: int):
    # Exercise safe_download's real raise_for_status path without accessing the network.
    async def resolve(hostname: str) -> list[str]:
        return ['93.184.216.34']

    async def send(client: httpx2.AsyncClient, request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, request=request, text='<title>Login</title>')

    monkeypatch.setattr(_ssrf, 'resolve_hostname', resolve)
    monkeypatch.setattr(_ssrf, '_send_request', send)
    result = await links.read_link('https://harbor.example/')
    assert f'answered {status}' in result and 'title: Login' not in result


async def test_private_addresses_are_refused():
    with pytest.raises(links.LinkError, match='could not read'):
        await links.read_link('http://127.0.0.1:9/')


async def test_stylesheets_and_images_are_bounded(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, int]] = []

    async def download(url: str, **kwargs: Any) -> httpx2.Response:
        calls.append((url, kwargs['max_bytes']))
        if url.endswith('.css'):
            return httpx2.Response(200, text='h1{color:#ff6b4a}', request=httpx2.Request('GET', url))
        return httpx2.Response(
            200,
            text='<title>Brand</title><link rel="stylesheet" href="/brand.css">',
            headers={'content-type': 'text/html'},
            request=httpx2.Request('GET', url),
        )

    monkeypatch.setattr(links, 'download', download)
    result = await links.read_link('https://harbor.example/')
    assert '#ff6b4a' in result
    assert calls == [
        ('https://harbor.example/', links.PAGE_MAX_BYTES),
        ('https://harbor.example/brand.css', links.SHEET_MAX_BYTES),
    ]
    with pytest.raises(links.LinkError, match='expected a PNG'):
        await links.download_image('https://harbor.example/not-an-image')
