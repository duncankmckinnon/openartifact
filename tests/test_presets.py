"""Reusable snapshots keep content independent and apply styles without damaging existing files."""

from __future__ import annotations

import asyncio
import threading
import tomllib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import presets
import pytest

import auth
import build
import db
import store
import workspace

pytestmark = pytest.mark.anyio


async def test_draft_is_unlisted_until_saved(principal: auth.Principal):
    draft = await presets.create(principal.workspace_id, 'Brand', 'deck', kind='template', draft=True)
    assert draft.draft
    assert await workspace.list_artifacts(principal.workspace_id) == []
    result = await presets.save_draft(draft, 'Harbor')
    assert (result.id, result.draft, result.title) == (draft.id, False, 'Harbor')
    assert await workspace.list_artifacts(principal.workspace_id) == [result]
    async with workspace.open_artifact(result) as directory:
        assert build.load_config(directory).title == 'Harbor'


async def test_saving_a_broken_draft_is_refused_and_kept(principal: auth.Principal):
    draft = await presets.create(principal.workspace_id, 'Brand', 'deck', kind='template', draft=True)
    async with workspace.edit(draft.id, 'broken source') as tx:
        (tx.path / 'main.md').write_text('# {{ UNKNOWN }}\n')
    before = await presets.saved(draft.id)
    with pytest.raises(build.BuildError, match='UNKNOWN'):
        await presets.save_draft(draft, 'Changed title')
    assert await presets.saved(draft.id) == before
    async with workspace.open_artifact(before) as directory:
        assert build.load_config(directory).title == 'Brand'
        assert 'UNKNOWN' in (directory / 'main.md').read_text()


async def test_save_upload_failure_keeps_the_original_draft(principal: auth.Principal, monkeypatch: pytest.MonkeyPatch):
    draft = await presets.create(principal.workspace_id, 'Brand', 'page', kind='style', draft=True)

    async def unavailable(self: store.ObjectStore, key: str, data: bytes) -> None:
        raise OSError('store unavailable')

    monkeypatch.setattr(store.ObjectStore, 'put', unavailable)
    with pytest.raises(OSError, match='store unavailable'):
        await presets.save_draft(draft, 'Harbor')
    assert await presets.saved(draft.id) == draft
    async with workspace.open_artifact(draft) as directory:
        assert build.load_config(directory).title == 'Brand'


async def test_discard_deletes_the_draft(principal: auth.Principal):
    draft = await presets.create(principal.workspace_id, 'Brand', 'page', kind='style', draft=True)
    await presets.discard_draft(draft)
    assert await workspace.get_artifact(draft.id) is None


async def test_saved_entry_cannot_be_discarded_with_a_stale_draft(principal: auth.Principal):
    draft = await presets.create(principal.workspace_id, 'Brand', 'page', kind='style', draft=True)
    saved = await presets.save_draft(draft, 'Brand')
    with pytest.raises(build.BuildError, match='draft'):
        await presets.discard_draft(draft)
    with pytest.raises(build.BuildError, match='draft'):
        await presets.save_draft(draft, 'Another title')
    assert await presets.saved(draft.id) == saved


async def test_save_holds_the_row_lock_during_validation(principal: auth.Principal, monkeypatch: pytest.MonkeyPatch):
    draft = await presets.create(principal.workspace_id, 'Brand', 'page', kind='style', draft=True)
    validating, finish = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    validate = build.build_page_data

    def paused_validation(cfg: build.Config, *, css_validator: build.CssValidator | None = None) -> dict[str, object]:
        loop.call_soon_threadsafe(validating.set)
        if not finish.wait(5):
            raise TimeoutError('test did not release validation')
        return validate(cfg, css_validator=css_validator)

    monkeypatch.setattr(build, 'build_page_data', paused_validation)
    task = asyncio.create_task(presets.save_draft(draft, 'Harbor'))
    try:
        await asyncio.wait_for(validating.wait(), 5)
        async with db.pool().acquire() as conn, conn.transaction():
            with pytest.raises(asyncpg.LockNotAvailableError):
                await conn.fetchrow('SELECT id FROM artifacts WHERE id = $1 FOR UPDATE NOWAIT', draft.id)
    finally:
        finish.set()
        result = await asyncio.wait_for(task, 5)
    assert not result.draft and result.title == 'Harbor'


async def test_sweep_deletes_only_idle_drafts(principal: auth.Principal):
    idle = await presets.create(principal.workspace_id, 'Idle', 'page', kind='style', draft=True)
    fresh = await presets.create(principal.workspace_id, 'Fresh', 'page', kind='style', draft=True)
    saved = await presets.create(principal.workspace_id, 'Saved', 'page', kind='style')
    await db.pool().execute(
        "UPDATE artifacts SET updated_at = now() - interval '25 hours' WHERE id = ANY($1::uuid[])",
        [idle.id, saved.id],
    )
    assert await presets.sweep_drafts() == 1
    assert await workspace.get_artifact(idle.id) is None
    assert await workspace.get_artifact(fresh.id) is not None
    assert await workspace.get_artifact(saved.id) is not None


@pytest.mark.parametrize('change', ['edit', 'save'])
async def test_sweep_rechecks_candidates_after_changes(
    principal: auth.Principal, monkeypatch: pytest.MonkeyPatch, change: str
):
    draft = await presets.create(principal.workspace_id, 'Brand', 'page', kind='style', draft=True)
    await db.pool().execute("UPDATE artifacts SET updated_at = now() - interval '25 hours' WHERE id = $1", draft.id)
    selected, changed = asyncio.Event(), asyncio.Event()
    delete = workspace.delete_artifact

    async def after_change(
        artifact_id: uuid.UUID,
        *,
        draft_workspace_id: uuid.UUID | None = None,
        expired_before: datetime | None = None,
    ) -> bool:
        selected.set()
        await changed.wait()
        return await delete(artifact_id, draft_workspace_id=draft_workspace_id, expired_before=expired_before)

    monkeypatch.setattr(workspace, 'delete_artifact', after_change)
    task = asyncio.create_task(presets.sweep_drafts())
    try:
        await asyncio.wait_for(selected.wait(), 5)
        if change == 'edit':
            async with workspace.edit(draft.id, 'still editing') as tx:
                (tx.path / 'main.md').write_text('# Still editing\n')
        else:
            await presets.save_draft(draft, 'Keep me')
    finally:
        changed.set()
        count = await asyncio.wait_for(task, 5)
    assert count == 0
    found = await presets.saved(draft.id)
    assert found.updated_at > datetime.now(UTC) - timedelta(hours=1)
    assert found.draft == (change == 'edit')


async def test_sweep_retries_cleanup_after_row_deletion(
    principal: auth.Principal, storage: store.ObjectStore, monkeypatch: pytest.MonkeyPatch
):
    draft = await presets.create(principal.workspace_id, 'Brand', 'page', kind='style', draft=True)
    async with workspace.edit(draft.id, 'second version') as tx:
        (tx.path / 'main.md').write_text('# Updated\n')
    assert len(await storage.list(f'artifacts/{draft.id}/')) == 2
    delete = store.ObjectStore.delete
    attempts = 0

    async def unavailable(self: store.ObjectStore, key: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise OSError('store unavailable')
        await delete(self, key)

    monkeypatch.setattr(store.ObjectStore, 'delete', unavailable)
    # Discard succeeds logically even when external cleanup must be retried.
    await presets.discard_draft(draft)
    assert await workspace.get_artifact(draft.id) is None
    assert len(await storage.list(f'artifacts/{draft.id}/')) == 1
    assert await db.pool().fetchval('SELECT artifact_id FROM artifact_deletions') == draft.id
    monkeypatch.setattr(store.ObjectStore, 'delete', delete)
    assert await presets.sweep_drafts() == 0
    assert await storage.list(f'artifacts/{draft.id}/') == []
    assert not workspace.checkout_path(draft.id).parent.exists()
    assert not await db.pool().fetchval('SELECT EXISTS (SELECT FROM artifact_deletions)')


async def source_artifact(principal: auth.Principal, tmp_path: Path) -> workspace.Artifact:
    """An artifact with custom paths, a component, and CSS that uses local font and image assets."""
    directory = tmp_path / 'source'
    (directory / 'text').mkdir(parents=True)
    (directory / 'assets').mkdir()
    (directory / 'components').mkdir()
    (directory / 'artifact.toml').write_text(
        'title = "Original"\ntype = "document"\ntheme = "dark"\n'
        'markdown = "text/body.md"\nstyles = "look.css"\npage_component = "Frame.html"\n'
        '[context]\nAUTHOR = "Alice"\n[extra]\ntitle = "Keep this"\n'
    )
    (directory / 'text/body.md').write_text('# Original\n\nPrivate source content.\n')
    (directory / 'look.css').write_text(
        '@font-face {font-family: custom; src: url("assets/font.woff2?v=1")}\n'
        '.page {background-image: url(assets/mark.svg#logo); color: red}\n'
    )
    (directory / 'components/Frame.html').write_text('<header>{{ AUTHOR }}</header>{{ CONTENT }}')
    (directory / 'assets/font.woff2').write_bytes(b'font bytes')
    (directory / 'assets/mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    return await workspace.import_directory(principal.workspace_id, 'Original', 'document', directory)


async def test_template_is_an_independent_snapshot_with_custom_paths(principal: auth.Principal, tmp_path: Path):
    source = await source_artifact(principal, tmp_path)
    template = await presets.save(source, principal.workspace_id, 'Reusable report', 'template')
    assert (template.preset_kind, template.visibility, template.organization_id) == ('template', 'private', None)
    async with workspace.edit(source.id, 'change original') as tx:
        (tx.path / 'text/body.md').write_text('# Changed original\n')
    result = await presets.instantiate(template, principal.workspace_id, title='Quarterly', content='# Q4\n')
    async with workspace.open_artifact(result) as directory:
        cfg = build.load_config(directory)
        assert (cfg.title, cfg.type, cfg.theme, cfg.page_component, cfg.context) == (
            'Quarterly',
            'document',
            'dark',
            'Frame.html',
            {'AUTHOR': 'Alice'},
        )
        assert cfg.markdown_path.read_text() == '# Q4\n'
        assert (directory / 'assets/font.woff2').read_bytes() == b'font bytes'
        assert tomllib.loads((directory / 'artifact.toml').read_text())['extra']['title'] == 'Keep this'
    async with workspace.open_artifact(template) as directory:
        assert 'Private source content.' in (directory / 'text/body.md').read_text()
    assert result.preset_kind is None
    assert len((await workspace.artifact_git(result.id, 'log', '--oneline')).splitlines()) == 1


async def test_style_copies_only_appearance_and_namespaces_assets(principal: auth.Principal, tmp_path: Path):
    source = await source_artifact(principal, tmp_path)
    style = await presets.save(source, principal.workspace_id, 'My brand', 'style')
    async with workspace.open_artifact(style) as directory:
        assert 'Private source content.' not in (directory / 'main.md').read_text()
        assert not (directory / 'components').exists()
        assert (directory / 'assets/font.woff2').is_file()
    target = await presets.create(principal.workspace_id, 'Target', 'page', kind='template')
    async with workspace.edit(target.id, 'existing asset') as tx:
        (tx.path / 'assets').mkdir()
        (tx.path / 'assets/mark.svg').write_text('keep existing asset')
    await presets.apply_style(target, style)
    async with workspace.open_artifact(target) as directory:
        cfg = build.load_config(directory)
        assert (cfg.type, cfg.theme) == ('page', 'dark')
        assert cfg.markdown_path.read_text().startswith('# Your page')
        assert (directory / 'assets/mark.svg').read_text() == 'keep existing asset'
        css = cfg.styles_path.read_text()
        assert '?v=1' in css and '#logo' in css
        assert 'url("assets/font.woff2' not in css
        for match in build.CSS_URL_RE.finditer(css):
            assert (directory / match.group('path').split('?')[0].split('#')[0]).is_file()


@pytest.mark.parametrize('css', ['@import "other.css";', '.page {background:url(../secret.png)}', '</style>'])
async def test_invalid_style_does_not_create_a_library_entry(principal: auth.Principal, css: str):
    with pytest.raises(build.BuildError):
        await presets.create(principal.workspace_id, 'Broken', 'page', css=css, kind='style')
    assert await workspace.list_artifacts(principal.workspace_id) == []


async def test_invalid_apply_rolls_back_and_library_removal_keeps_artifact(principal: auth.Principal):
    style = await presets.create(principal.workspace_id, 'Brand', 'page', css=':root {--accent: red}', kind='style')
    target = await presets.create(principal.workspace_id, 'Template', 'page', kind='template')
    original_head = target.head_sha
    async with workspace.edit(style.id, 'bad stylesheet') as tx:
        (tx.path / 'styles.css').write_text('p {background: url(missing.png)}')
    with pytest.raises(build.BuildError):
        await presets.apply_style(target, style)
    current = await workspace.get_artifact(target.id)
    assert current is not None and current.head_sha == original_head
    await presets.remove(target)
    current = await workspace.get_artifact(target.id)
    assert current is not None and current.preset_kind is None and current.head_sha == original_head


async def test_snapshot_rejects_symlinks(principal: auth.Principal, tmp_path: Path):
    source = await source_artifact(principal, tmp_path)
    async with workspace.edit(source.id, 'unsafe link') as tx:
        (tx.path / 'linked').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(build.BuildError, match='symlink'):
        await presets.save(source, principal.workspace_id, 'Unsafe', 'template')


async def test_encoded_absolute_asset_is_a_build_error(principal: auth.Principal):
    with pytest.raises(build.BuildError, match='escapes'):
        await presets.create(
            principal.workspace_id, 'Unsafe', 'page', kind='style', css='p {background:url(%2Ftmp%2Foutside.svg)}'
        )


async def test_style_cannot_overwrite_markdown(principal: auth.Principal):
    target = await presets.create(principal.workspace_id, 'Target', 'page', kind='template')
    style = await presets.create(principal.workspace_id, 'Red', 'page', kind='style', css='p {color:red}')
    async with workspace.edit(target.id, 'conflicting source paths') as tx:
        presets.configure(tx.path, styles='main.md')
    with pytest.raises(build.BuildError, match='markdown'):
        await presets.apply_style(target, style)


async def test_css_scanner_copies_quoted_urls_and_ignores_comments(principal: auth.Principal, tmp_path: Path):
    source = await source_artifact(principal, tmp_path)
    css = """/* Old font: url("missing.woff2") */
.page::after {content: "url(missing.svg)"}
.page {background: url("assets/logo (1).svg#icon")}
.prose {background: url("assets/it's.svg")}
"""
    async with workspace.edit(source.id, 'quoted CSS assets') as tx:
        (tx.path / 'assets/logo (1).svg').write_text('<svg/>')
        (tx.path / "assets/it's.svg").write_text('<svg/>')
        (tx.path / 'look.css').write_text(css)
    style = await presets.save(source, principal.workspace_id, 'Quoted assets', 'style')
    target = await presets.create(principal.workspace_id, 'Target', 'page', kind='template')
    await presets.apply_style(target, style)
    async with workspace.open_artifact(target) as directory:
        copies = list((directory / 'assets').rglob('*.svg'))
        assert sorted(p.name for p in copies) == ["it's.svg", 'logo (1).svg']
        result = build.load_config(directory).styles_path.read_text()
        assert 'missing.woff2' in result and 'url(missing.svg)' in result
        assert 'url("assets/logo (1).svg' not in result
        assert '%20' in result and '#icon' in result


async def test_css_import_text_and_empty_urls_are_not_dependencies(principal: auth.Principal):
    style = await presets.create(
        principal.workspace_id,
        'CSS examples',
        'page',
        kind='style',
        css='.page::after {content: "Use @import carefully"} .page {background: url()}',
    )
    assert style.preset_kind == 'style'


async def test_saved_style_copies_and_rewrites_image_set_assets(principal: auth.Principal, tmp_path: Path):
    source = await source_artifact(principal, tmp_path)
    async with workspace.edit(source.id, 'responsive background') as tx:
        (tx.path / 'look.css').write_text(
            r'.page {background: image-set("assets/mark.svg#logo" 1x, u\72l("assets/mark.svg") 2x)}'
        )
    style = await presets.save(source, principal.workspace_id, 'Responsive', 'style')
    target = await presets.create(principal.workspace_id, 'Target', 'page', kind='template')
    await presets.apply_style(target, style)
    async with workspace.open_artifact(target) as directory:
        images = list((directory / 'assets').rglob('mark.svg'))
        assert len(images) == 1 and images[0].read_text().startswith('<svg')
        css = build.load_config(directory).styles_path.read_text()
        assert 'image-set(' in css and '#logo' in css
        assert '"assets/mark.svg' not in css


async def test_applying_style_preserves_escaped_sample_text(principal: auth.Principal):
    style = await presets.create(
        principal.workspace_id,
        'Code samples',
        'page',
        kind='style',
        css=r'.page::after {content: "\3c /style>"}',
    )
    target = await presets.create(principal.workspace_id, 'Target', 'page', kind='template')
    await presets.apply_style(target, style)
    async with workspace.open_artifact(target) as directory:
        css = build.load_config(directory).styles_path.read_text()
        build.check_styles(css, directory / 'styles.css')
        assert (directory / 'dist/index.html').is_file()


def test_saved_style_bounds_asset_bytes_before_reading(tmp_path: Path):
    (tmp_path / 'main.md').write_text('# Preview\n')
    (tmp_path / 'styles.css').write_text('p {background: url(large.png)}')
    with (tmp_path / 'large.png').open('wb') as asset:
        asset.truncate(20_000_001)
    with pytest.raises(build.BuildError, match='20 MB'):
        presets.style_files(tmp_path)


def test_saved_style_bounds_local_asset_count(tmp_path: Path):
    (tmp_path / 'main.md').write_text('# Preview\n')
    for index in range(257):
        (tmp_path / f'image{index}.svg').write_text('<svg/>')
    (tmp_path / 'styles.css').write_text('p {background: ' + ','.join(f'url(image{i}.svg)' for i in range(257)) + '}')
    with pytest.raises(build.BuildError, match='256'):
        presets.style_files(tmp_path)
