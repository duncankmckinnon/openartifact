"""Thumbnail version consistency and concurrent request coalescing."""

from __future__ import annotations

import asyncio

import presets
import pytest
import render

import auth
import workspace

pytestmark = pytest.mark.anyio


async def test_concurrent_thumbnails_share_one_render(principal: auth.Principal, monkeypatch: pytest.MonkeyPatch):
    entry = await presets.create(principal.workspace_id, 'Thumb', 'page', kind='style')
    calls = 0

    async def chrome(endpoint: str, body: dict[str, object]) -> bytes:
        nonlocal calls
        calls += 1
        assert body['scale'] == 0.5
        await asyncio.sleep(0)
        return b'png'

    monkeypatch.setattr(render, 'call_chrome', chrome)
    assert await asyncio.gather(render.thumbnail(entry), render.thumbnail(entry)) == [b'png', b'png']
    assert calls == 1


async def test_edit_during_render_cannot_publish_an_old_version(
    principal: auth.Principal, monkeypatch: pytest.MonkeyPatch
):
    entry = await presets.create(principal.workspace_id, 'Thumb', 'page', kind='style')

    async def chrome(endpoint: str, body: dict[str, object]) -> bytes:
        async with workspace.edit(entry.id, 'concurrent edit') as tx:
            (tx.path / 'main.md').write_text('# Changed\n')
        return b'newer image'

    monkeypatch.setattr(render, 'call_chrome', chrome)
    with pytest.raises(render.RenderError, match='changed while rendering'):
        await render.thumbnail(entry)
    assert not list(workspace.checkout_path(entry.id).parent.glob('thumbnail-*'))


async def test_style_screenshot_uses_guide_types(principal: auth.Principal, monkeypatch: pytest.MonkeyPatch):
    entry = await presets.create(principal.workspace_id, 'Guide', 'page', kind='style')

    async def chrome(endpoint: str, body: dict[str, object]) -> bytes:
        assert '?guide&type=document' in str(body['url'])
        return b'png'

    monkeypatch.setattr(render, 'call_chrome', chrome)
    assert await render.screenshot(entry, 2) == b'png'
    with pytest.raises(render.RenderError, match='three pages'):
        await render.screenshot(entry, 4)
