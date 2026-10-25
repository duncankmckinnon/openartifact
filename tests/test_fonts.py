"""Google font installation uses allowlisted bounded downloads and produces portable CSS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fonts
import httpx2
import pytest
import styles
from pydantic_ai import _ssrf

pytestmark = pytest.mark.anyio


def test_slug():
    assert fonts.slug('Source Serif 4') == 'source-serif-4'
    with pytest.raises(fonts.FontError):
        fonts.slug('../bad')


async def test_latin_subsets_and_local_css(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: list[dict[str, Any]] = []

    async def download(url: str, **kwargs: Any) -> httpx2.Response:
        calls.append(kwargs)
        css = '\n'.join(
            f'/* {subset} */\n@font-face{{font-family:Inter;font-style:normal;font-weight:400;src:url(https://fonts.gstatic.com/{subset}.woff2);unicode-range:U+0-FF}}'
            for subset in ('cyrillic', 'latin-ext', 'latin')
        )
        return httpx2.Response(
            200, content=css.encode() if 'googleapis' in url else b'wOF2font', request=httpx2.Request('GET', url)
        )

    monkeypatch.setattr(fonts, 'download', download)
    files = await fonts.fetch_family('Inter', [400], False)
    assert [f.path for f in files] == ['fonts/inter-400-latin-ext.woff2', 'fonts/inter-400-latin.woff2']
    assert calls[0]['allowed_domains'] == ['fonts.googleapis.com']
    assert all(c['max_redirects'] == 0 and c['max_bytes'] for c in calls)
    for file in files:
        path = tmp_path / file.path
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(file.data)
    css = fonts.font_face_css('Inter', files)
    styles.validate(css, tmp_path)
    assert 'unicode-range: U+0-FF' in css


@pytest.mark.parametrize(
    'url',
    [
        'https://evil.example/font.woff2',
        'http://fonts.gstatic.com/font.woff2',
        'https://fonts.gstatic.com.evil.example/font.woff2',
    ],
)
async def test_foreign_or_insecure_font_urls_are_refused(monkeypatch: pytest.MonkeyPatch, url: str):
    async def download(address: str, **kwargs: Any) -> httpx2.Response:
        assert 'googleapis' in address  # No attempt to fetch the foreign URL.
        return httpx2.Response(
            200, text=f'/* latin */@font-face{{font-weight:400;src:url({url})}}', request=httpx2.Request('GET', address)
        )

    monkeypatch.setattr(fonts, 'download', download)
    with pytest.raises(fonts.FontError, match='unexpected font host'):
        await fonts.fetch_family('Inter', [400], False)


async def test_unknown_family_is_reported(monkeypatch: pytest.MonkeyPatch):
    async def download(url: str, **kwargs: Any) -> httpx2.Response:
        response = httpx2.Response(400, request=httpx2.Request('GET', url))
        response.raise_for_status()
        return response

    monkeypatch.setattr(fonts, 'download', download)
    with pytest.raises(fonts.FontError, match='not a Google Fonts family'):
        await fonts.fetch_family('Unknown', [400], False)


async def test_real_downloader_does_not_follow_font_redirects(monkeypatch: pytest.MonkeyPatch):
    calls = 0

    async def resolve(hostname: str) -> list[str]:
        return ['93.184.216.34']

    async def send(client: httpx2.AsyncClient, request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(302, headers={'location': 'http://127.0.0.1/private'}, request=request)

    monkeypatch.setattr(_ssrf, 'resolve_hostname', resolve)
    monkeypatch.setattr(_ssrf, '_send_request', send)
    with pytest.raises(fonts.FontError, match='redirects'):
        await fonts.fetch_family('Inter', [400], False)
    assert calls == 1
