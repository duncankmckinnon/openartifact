"""Personal templates and styles backed by independent, versioned artifact snapshots."""

from __future__ import annotations

import asyncio
import json
import re
import tomllib
import uuid
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote, unquote, urlsplit

import access
import build
import db
import workspace

Kind = Literal['template', 'style']
STYLE_PREVIEW = '# Your style\n\nA reusable visual style.\n\n## A heading\n\nText with **bold**, *italic*, and a [link](#).\n\n- First item\n- Second item\n'


def name_of(name: str) -> str:
    """Require a usable library name before creating any files."""
    name = name.strip()
    if not name or len(name) > 200:
        raise build.BuildError('name must contain 1 to 200 characters')
    return name


def contained(directory: Path, path: Path) -> Path:
    """Reject paths outside the source tree and symlinks anywhere along a path."""
    root = directory.resolve()
    try:
        relative = path.relative_to(directory)
    except ValueError:
        try:
            relative = path.relative_to(root)
        except ValueError:
            raise build.BuildError(f'path escapes the artifact: {path.name}') from None
    path = root / relative
    if '..' in path.parts:
        raise build.BuildError(f'path escapes the artifact: {path.name}')
    if path.is_symlink():
        raise build.BuildError(f'symlinks cannot be copied: {path.name}')
    if not path.resolve().is_relative_to(root):
        raise build.BuildError(f'path escapes the artifact: {path.name}')
    current = path
    while current != root:
        if current.is_symlink():
            raise build.BuildError(f'symlinks cannot be copied: {current.name}')
        current = current.parent
    return path


def configuration(directory: Path) -> build.Config:
    """Load a configuration whose source paths are safe to copy and edit."""
    contained(directory, directory / 'artifact.toml')
    cfg = build.load_config(directory)
    config_path = directory / 'artifact.toml'
    if config_path.is_file():
        raw = tomllib.loads(config_path.read_text(encoding='utf-8'))
        for key in ('markdown', 'styles', 'components', 'favicon'):
            value = raw.get(key)
            if isinstance(value, str) and Path(value).is_absolute():
                raise build.BuildError(f'{key} must be a relative path inside the artifact')
    for path in (cfg.markdown_path, cfg.styles_path, cfg.components_dir):
        contained(directory, path)
    if cfg.favicon:
        contained(directory, directory / cfg.favicon)
    return cfg


def toml_value(value: object) -> str:
    """Serialize stdlib TOML values, using inline tables to preserve unknown configuration fields."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return '[' + ', '.join(toml_value(v) for v in cast(list[object], value)) + ']'
    if isinstance(value, dict):
        return (
            '{'
            + ', '.join(f'{json.dumps(k)} = {toml_value(v)}' for k, v in cast(dict[str, object], value).items())
            + '}'
        )
    raise build.BuildError(f'unsupported configuration value: {value!r}')


def configure(directory: Path, **changes: str) -> None:
    """Update top-level settings without confusing them with identically named table keys."""
    path = directory / 'artifact.toml'
    raw = tomllib.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    raw.update(changes)
    path.write_text(''.join(f'{toml_key(k)} = {toml_value(v)}\n' for k, v in raw.items()), encoding='utf-8')


def toml_key(key: str) -> str:
    """Keep ordinary configuration keys compatible with the existing title editor."""
    return key if re.fullmatch(r'[A-Za-z0-9_-]+', key) else json.dumps(key)


def style_files(directory: Path) -> tuple[str, str, dict[str, bytes]]:
    """Read CSS and its local assets; imports require bundling before saving a style."""
    cfg = configuration(directory)
    css = cfg.styles_path.read_text(encoding='utf-8') if cfg.styles_path.is_file() else ''
    build.check_styles(css, cfg.styles_path)
    if re.search(r'@import\b', build.CSS_TOKEN_RE.sub(' ', css), re.IGNORECASE):
        raise build.BuildError('CSS @import is not supported in saved styles; combine the stylesheets first')
    files: dict[str, bytes] = {}
    for url in build.css_urls(css):
        raw = url.path
        if not raw or raw.startswith('#') or build.is_external(raw):
            continue
        key = unquote(urlsplit(raw).path)
        if Path(key).suffix.lower() not in (*build.IMAGE_EXTS, '.woff', '.woff2'):
            raise build.BuildError(f'unsupported style asset: {raw!r}; use an image or WOFF font')
        path = contained(directory, directory / key)
        if not key or not path.is_file():
            raise build.BuildError(f'style asset not found: {raw!r}')
        # Canonical keys ensure a CSS URL with ./ or percent escaping maps to the copied file.
        files[path.relative_to(directory).as_posix()] = path.read_bytes()
    return css, cfg.theme, files


def snapshot(directory: Path) -> dict[str, bytes]:
    """Validate and copy only source files, without history or derived output."""
    cfg = configuration(directory)
    files: dict[str, bytes] = {}
    for path in directory.rglob('*'):
        relative = path.relative_to(directory)
        if relative.parts[0] == 'dist' or any(part.startswith('.git') for part in relative.parts):
            continue
        contained(directory, path)
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    build.build_page_data(cfg)
    return files


def write_files(directory: Path, files: dict[str, bytes]) -> None:
    """Write a previously checked source snapshot into a new artifact tree."""
    for key, data in files.items():
        path = contained(directory, directory / key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def install_style(directory: Path, css: str, theme: str, files: dict[str, bytes]) -> None:
    """Replace appearance and namespace its assets so existing content keeps its own files."""
    cfg = configuration(directory)
    if cfg.styles_path.resolve() == cfg.markdown_path.resolve():
        raise build.BuildError('the stylesheet path must be different from the markdown path')
    prefix = f'assets/style-{uuid.uuid4().hex}'
    write_files(directory, {f'{prefix}/{key}': data for key, data in files.items()})

    def replace(url: build.CssUrl) -> str:
        raw = url.path
        if not raw or raw.startswith('#') or build.is_external(raw):
            return css[url.start : url.end]
        parts = urlsplit(raw)
        key = Path(unquote(parts.path)).as_posix()
        rewritten = quote(f'{prefix}/{key}', safe='/')
        if parts.query:
            rewritten += f'?{parts.query}'
        if parts.fragment:
            rewritten += f'#{parts.fragment}'
        return f'url({json.dumps(rewritten, ensure_ascii=False)})'

    cfg.styles_path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    end = 0
    for url in build.css_urls(css):
        parts.extend((css[end : url.start], replace(url)))
        end = url.end
    parts.append(css[end:])
    cfg.styles_path.write_text(''.join(parts), encoding='utf-8')
    configure(directory, theme=theme)


async def saved(artifact_id: uuid.UUID) -> workspace.Artifact:
    """Load an artifact after its creation transaction commits."""
    result = await workspace.get_artifact(artifact_id)
    assert result is not None
    return result


async def save(source: workspace.Artifact, workspace_id: uuid.UUID, name: str, kind: Kind) -> workspace.Artifact:
    """Save a private, independent template or content-free style snapshot."""
    name = name_of(name)
    async with workspace.open_artifact(source) as directory:
        if kind == 'style':
            css, theme, files = await asyncio.to_thread(style_files, directory)
        else:
            files = await asyncio.to_thread(snapshot, directory)
            css, theme = '', 'light'
    artifact_id = uuid.uuid4()
    create = workspace.NewArtifact(workspace_id, name, 'page' if kind == 'style' else source.type, preset_kind=kind)
    async with workspace.edit(artifact_id, f'save {kind}: {name}', create=create) as tx:
        if kind == 'style':
            (tx.path / 'main.md').write_text(STYLE_PREVIEW, encoding='utf-8')
            configure(tx.path, title=name, type='page', theme=theme)
            write_files(tx.path, files)
            (tx.path / 'styles.css').write_text(css, encoding='utf-8')
        else:
            write_files(tx.path, files)
            cfg = configuration(tx.path)
            configure(tx.path, title=name)
            await tx.conn.execute('UPDATE artifacts SET type = $2 WHERE id = $1', artifact_id, cfg.type)
        await asyncio.to_thread(build.build_html, tx.path, markdown_url=f'../{artifact_id}.md')
    return await saved(artifact_id)


async def create(
    workspace_id: uuid.UUID, name: str, type: str, *, kind: Kind, css: str | None = None, theme: str = 'light'
) -> workspace.Artifact:
    """Create a private starter template or a style from pasted CSS."""
    # Import here: agent's defaults depend on the MCP module, which also calls these helpers.
    import agent

    name = name_of(name)
    artifact_id = uuid.uuid4()
    create = workspace.NewArtifact(workspace_id, name, type, preset_kind=kind)
    async with workspace.edit(artifact_id, f'new {kind}: {name}', create=create) as tx:
        configure(tx.path, title=name, type=type, theme=theme)
        (tx.path / 'main.md').write_text(
            STYLE_PREVIEW if kind == 'style' else agent.STARTER_CONTENT[type], encoding='utf-8'
        )
        (tx.path / 'styles.css').write_text(css if css is not None else agent.STARTER_STYLES[type], encoding='utf-8')
        if kind == 'style':
            await asyncio.to_thread(style_files, tx.path)
        await asyncio.to_thread(build.build_html, tx.path, markdown_url=f'../{artifact_id}.md')
    return await saved(artifact_id)


async def instantiate(
    source: workspace.Artifact,
    workspace_id: uuid.UUID,
    *,
    title: str | None = None,
    content: str | None = None,
    style: workspace.Artifact | None = None,
    visibility: str = 'private',
    organization_id: uuid.UUID | None = None,
    org_editable: bool = False,
) -> workspace.Artifact:
    """Make an independent artifact from a template and optionally apply a saved style, atomically."""
    problem = access.check_access(visibility, org_editable, organization_id)
    if problem:
        raise build.BuildError(problem)
    title = name_of(title or source.title)
    async with workspace.open_artifact(source) as directory:
        files = await asyncio.to_thread(snapshot, directory)
        type = configuration(directory).type
    appearance = None
    if style is not None:
        async with workspace.open_artifact(style) as directory:
            appearance = await asyncio.to_thread(style_files, directory)
    artifact_id = uuid.uuid4()
    create = workspace.NewArtifact(workspace_id, title, type, visibility, org_editable, organization_id, source.id)
    async with workspace.edit(artifact_id, f'from template: {source.id}', create=create) as tx:
        write_files(tx.path, files)
        configure(tx.path, title=title)
        if content is not None:
            configuration(tx.path).markdown_path.write_text(content, encoding='utf-8')
        if appearance is not None:
            install_style(tx.path, *appearance)
        await asyncio.to_thread(build.build_html, tx.path, markdown_url=f'../{artifact_id}.md')
    return await saved(artifact_id)


async def apply_style(target: workspace.Artifact, style: workspace.Artifact) -> None:
    """Apply a saved style in one validated edit, leaving the target's content and layout intact."""
    async with workspace.open_artifact(style) as directory:
        appearance = await asyncio.to_thread(style_files, directory)
    async with workspace.edit(target.id, f'apply style: {style.title}') as tx:
        install_style(tx.path, *appearance)
        await asyncio.to_thread(build.build_html, tx.path, markdown_url=f'../{target.id}.md')


async def remove(entry: workspace.Artifact) -> None:
    """Remove library membership while retaining the artifact and its history."""
    await db.pool().execute('UPDATE artifacts SET preset_kind = NULL WHERE id = $1', entry.id)
