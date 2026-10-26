"""Rendering an artifact's page through the chrome service: the PDF export, a screenshot of one page, and the
scene and slide pictures the PowerPoint export (`powerpoint.py`) is built from.

The chrome service (`chrome/`) runs Chrome headless against a URL this server serves. Chrome carries no session,
so it is sent to the print pass, `/print/{token}/artifacts/{id}/`, a short-lived signed URL (`print_token`) that
`server.py` answers with the page and its media. The page is built first, under the artifact lock, which is
released before the chrome service is called: Chrome fetches the page from this process, which takes the same
lock. `server.py` (the `.pdf` and `.png` routes), `mcp_server.py` (the `screenshot` tool) and `powerpoint.py` call
in here.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import httpx2
import styles

import build
import config
import signing
import workspace

PRINT_PURPOSE = b'openartifact print url'
# How long a print pass lives: the chrome service fetches the page within seconds of it being minted.
PRINT_TTL = 300
# The window a screenshot is taken in, per artifact type: a deck's 16:9 page fills it; a document's A4 sheet at
# 150 dpi; a page artifact's column with room to read.
VIEWPORTS: dict[str, tuple[int, int]] = {'deck': (1600, 900), 'document': (1240, 1754), 'page': (1280, 1600)}
GUIDE_PAGES = ('deck', 'document', 'page')
THUMBNAIL_SCALE = 0.5
CARD_VIEWPORT = (800, 450)
_thumbnail_locks: dict[tuple[int, uuid.UUID], asyncio.Lock] = {}


class RenderError(Exception):
    """The chrome service is not configured (503), unreachable or failed (502); `status` is the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def chrome_client() -> httpx2.AsyncClient:
    """The HTTP client for the chrome service; tests swap it for one wired to a stub app."""
    return httpx2.AsyncClient(timeout=60)


def print_token(artifact_id: uuid.UUID) -> str:
    """A pass for the chrome service to fetch one artifact's page for the next few minutes."""
    return signing.token(PRINT_PURPOSE, str(artifact_id), expires=int(time.time()) + PRINT_TTL)


def verify_print_token(token: str, artifact_id: uuid.UUID) -> None:
    """Raise `signing.SignatureError` unless `token` is a live pass for this artifact."""
    signing.verify(PRINT_PURPOSE, token, str(artifact_id))


def print_url(found: workspace.Artifact, page: int | None = None, scene: bool = False, guide: str | None = None) -> str:
    """The address the chrome service fetches the page at, with the page number as the hash when given, and
    `?scene` when the page is wanted in the runtime's scene mode (frontend/src/scene.ts), for the PowerPoint export."""
    url = f'{config.internal_url()}/print/{print_token(found.id)}/artifacts/{found.id}/'
    if guide:
        url += f'?guide&type={guide}'
    elif scene:
        url += '?scene'
    return f'{url}#{page}' if page is not None else url


async def ensure_built(found: workspace.Artifact, directory: Path) -> Path:
    """`dist/index.html`, built now if this process has not built the current version yet.

    A `build.BuildError` propagates. The page is served at `/artifacts/<id>/`, so the `.md` export it advertises
    is `../<id>.md`.
    """
    page = directory / 'dist' / 'index.html'
    if not page.is_file():
        await asyncio.to_thread(
            build.build_html, directory, markdown_url=f'../{found.id}.md', css_validator=styles.validate
        )
    return page


async def call_chrome(endpoint: str, body: dict[str, object]) -> bytes:
    """POST `body` to the chrome service's `endpoint` and return the file it answers with."""
    chrome_url = config.chrome_url()
    if chrome_url is None:
        raise RenderError(503, 'rendering is not configured: OPENARTIFACT_CHROME_URL names the chrome service')
    try:
        async with chrome_client() as client:
            response = await client.post(f'{chrome_url}{endpoint}', json=body)
    except httpx2.HTTPError as exc:
        raise RenderError(502, f'chrome service unreachable: {exc}') from exc
    if response.status_code != 200:
        raise RenderError(502, f'chrome service failed ({response.status_code}): {response.text}')
    return response.content


async def pdf(found: workspace.Artifact) -> bytes:
    """The artifact's page printed to PDF. The page is built first, so a broken artifact fails as a build error."""
    async with workspace.open_artifact(found) as directory:
        await ensure_built(found, directory)
    return await call_chrome('/pdf/', {'url': print_url(found)})


async def screenshot(found: workspace.Artifact, page: int) -> bytes:
    """A PNG of one page of the artifact as a viewer sees it, in the window `VIEWPORTS` gives the type."""
    if found.preset_kind == 'style' and page not in range(1, 4):
        raise RenderError(422, 'a style has three pages: its guide for deck, document and page')
    async with workspace.open_artifact(found) as directory:
        await ensure_built(found, directory)
    if found.preset_kind == 'style':
        width, height = VIEWPORTS['page']
        return await call_chrome(
            '/screenshot/', {'url': print_url(found, guide=GUIDE_PAGES[page - 1]), 'width': width, 'height': height}
        )
    width, height = VIEWPORTS.get(found.type, VIEWPORTS['deck'])
    return await call_chrome('/screenshot/', {'url': print_url(found, page), 'width': width, 'height': height})


async def thumbnail(found: workspace.Artifact) -> bytes:
    """Coalesce renders and cache only a version that stayed current throughout the Chrome request."""
    key = (id(asyncio.get_running_loop()), found.id)
    async with _thumbnail_locks.setdefault(key, asyncio.Lock()):
        current = await workspace.get_artifact(found.id)
        if current is None or current.head_sha != found.head_sha:
            raise RenderError(409, 'artifact changed; reload the library')
        base = config.cache_dir() / str(found.id)
        path = base / f'thumbnail-{found.head_sha}.png'
        if path.is_file():
            return await asyncio.to_thread(path.read_bytes)
        async with workspace.open_artifact(found) as directory:
            await ensure_built(found, directory)
        width, height = CARD_VIEWPORT if found.preset_kind == 'style' else VIEWPORTS[found.type]
        data = await call_chrome(
            '/screenshot/',
            {
                'url': print_url(found, guide='document') if found.preset_kind == 'style' else print_url(found, 1),
                'width': width,
                'height': height,
                'scale': THUMBNAIL_SCALE,
            },
        )
        async with workspace.artifact_lock(found.id):
            current = await workspace.get_artifact(found.id)
            if current is None or current.head_sha != found.head_sha:
                raise RenderError(409, 'artifact changed while rendering; reload the library')
            temp = path.with_suffix('.tmp')
            await asyncio.to_thread(temp.write_bytes, data)
            temp.replace(path)
            for old in base.glob('thumbnail-*.png'):
                if old != path:
                    old.unlink(missing_ok=True)
        return data
