"""The JSON API behind the web app (`frontend/app/`): who is signed in, the artifact list, creation and sharing,
and the editing chat, which streams a pydantic-ai agent's turn in the Vercel AI SDK protocol.

Everything here is for a browser with a session cookie (`login.py`): a visitor gets a JSON 401, a user without
the right to see or change an artifact a 403. Mutations check `login.same_origin` on top of the Lax cookie.
Errors are JSON, never redirects: the callers are `fetch`, not navigations (the SPA shell routes in `server.py`
redirect).

The chat: the browser sends one new user message per turn; the server holds the conversation (`chats.py`),
runs the agent (`agent.py`) with the stored history, streams the events back, and stores the whole history when
the turn completes. The agent's tools are the MCP server's own, in-process, acting as the signed-in user: the
principal is set inside the streamed generator, because that is the task the agent and its MCP session run in,
after the route function has already returned the response.
"""

from __future__ import annotations

import asyncio
import logging
import tomllib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

import presets
import styles
from fastapi import APIRouter, HTTPException, Request, Response
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, TypeAdapter
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.run import AgentRunResult
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import StepStartUIPart, UIMessage
from pydantic_ai.ui.vercel_ai.response_types import BaseChunk
from pydantic_ai.usage import UsageLimits

import access
import agent
import auth
import build
import chats
import config
import login
import mcp_server
import workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api')

UI_MESSAGES = TypeAdapter(list[UIMessage])


async def viewer_required(request: Request) -> auth.Principal:
    """The signed-in user, or a JSON 401."""
    viewer = await login.current_viewer(request)
    if viewer is None:
        raise HTTPException(401, 'sign in required')
    return viewer


def mutation(request: Request) -> None:
    """Refuse a state-changing request that did not come from a page of ours."""
    if not login.same_origin(request):
        raise HTTPException(403, 'cross-site request')


async def artifact_for(
    artifact_id: str, viewer: auth.Principal, *, edit: bool = False, manage: bool = False
) -> workspace.Artifact:
    """The artifact, if the viewer may see it (and edit or manage it, as asked); 404 or 403 otherwise."""
    try:
        parsed = uuid.UUID(artifact_id)
    except ValueError:
        raise HTTPException(404, f'invalid artifact id {artifact_id!r}') from None
    found = await workspace.get_artifact(parsed)
    if found is None or not access.can_view(found, viewer):
        raise HTTPException(404, f'artifact {artifact_id} not found')
    if manage and not access.can_manage(found, viewer):
        raise HTTPException(403, 'only the owner can change who may see this artifact')
    if edit and not access.can_edit(found, viewer):
        raise HTTPException(403, 'this artifact is shared with you read-only')
    return found


def artifact_json(
    found: workspace.Artifact, viewer: auth.Principal, owner_email: str | None = None
) -> dict[str, object]:
    return {
        'id': str(found.id),
        'title': found.title,
        'type': found.type,
        'visibility': found.visibility,
        'org_editable': found.org_editable,
        'forked_from': str(found.forked_from) if found.forked_from else None,
        'preset_kind': found.preset_kind,
        'created_at': found.created_at.isoformat(),
        'updated_at': found.updated_at.isoformat(),
        'owner_email': owner_email,
        'can_edit': access.can_edit(found, viewer),
        'can_manage': access.can_manage(found, viewer),
        'url': mcp_server.artifact_url(found.id),
    }


@router.get('/')
def index() -> dict[str, object]:
    """Where things are; the web app lives at `/`."""
    return {'mcp': '/mcp/', 'runtime': '/openartifact.js', 'login': '/login', 'app': '/'}


@router.get('/me')
async def me(request: Request) -> dict[str, object]:
    """The signed-in user and their organisation."""
    viewer = await viewer_required(request)
    organization = None
    if viewer.organization_id is not None:
        org = await workspace.get_organization(viewer.organization_id)
        organization = {'domain': org.domain, 'name': org.name} if org else None
    return {
        'viewer': {'name': viewer.name, 'email': viewer.email, 'picture': viewer.picture},
        'organization': organization,
    }


@router.get('/configure')
async def configure(request: Request) -> dict[str, object]:
    """The models the chat's picker offers and the default, and how an MCP client reaches this server.

    `mcp` is what the app's set-up snippets are made from: the endpoint URL and whether a client signs in with
    Google (`oauth`) or sends the development token (`token`, with the token itself).
    """
    await viewer_required(request)
    token = auth.dev_token()
    return {
        'mcp': {'url': f'{config.base_url()}/mcp/', 'auth': 'oauth' if token is None else 'token', 'token': token},
        'models': [{'id': m.id, 'name': m.name} for m in agent.configured_models()],
        'default': agent.default_model(),
    }


@router.get('/artifacts')
async def list_artifacts(request: Request) -> dict[str, object]:
    """The viewer's own artifacts and the ones their organisation shares with them."""
    viewer = await viewer_required(request)
    mine = await workspace.list_artifacts(viewer.workspace_id)
    shared = await workspace.list_shared_artifacts(viewer.org_ids, viewer.workspace_id)
    return {
        'mine': [artifact_json(a, viewer, viewer.email) for a in mine],
        'shared': [artifact_json(a, viewer, owner) for a, owner in shared],
    }


class NewArtifactBody(BaseModel):
    """What the app sends to create an artifact; everything but `type` has a default fit for the type (`agent.py`)."""

    type: mcp_server.ArtifactType | None = None
    title: str | None = None
    theme: mcp_server.Theme | None = None
    content: str | None = None
    placement: Literal['personal', 'org'] = 'personal'
    public: bool = False
    org_editable: bool = False
    template_id: str | None = None
    style_id: str | None = None


@router.post('/artifacts', status_code=201)
async def create_artifact(body: NewArtifactBody, request: Request) -> dict[str, object]:
    """Create an artifact the way the MCP tools do; a placeholder title, a theme and starter pages for the type
    unless given. The placeholder title is replaced after the chat's first turn (`agent.suggest_title`)."""
    mutation(request)
    viewer = await viewer_required(request)
    template = await preset_for(body.template_id, viewer, 'template') if body.template_id else None
    style = await preset_for(body.style_id, viewer, 'style') if body.style_id else None
    artifact_type = body.type or (template.type if template else 'deck')
    if template and body.type and body.type != template.type:
        raise HTTPException(400, 'a template keeps its artifact type')
    title = (body.title or '').strip() or (template.title if template else agent.DEFAULT_TITLES[artifact_type])
    theme = body.theme or agent.DEFAULT_THEMES[artifact_type]
    # The type's placeholder pages and stylesheet when no content is given; given content gets no stylesheet.
    content = body.content if body.content is not None else agent.STARTER_CONTENT[artifact_type]
    styles = None if body.content is not None else agent.STARTER_STYLES[artifact_type]
    if body.placement == 'org':
        if viewer.organization_id is None:
            raise HTTPException(400, 'your account is not in an organisation')
        organization_id = viewer.organization_id
        visibility = 'public' if body.public else 'org'
    else:
        organization_id = None
        visibility = 'public' if body.public else 'private'
    try:
        if template is not None:
            if body.theme is not None:
                raise HTTPException(400, 'choose a saved style to override a template theme')
            found = await presets.instantiate(
                template,
                viewer.workspace_id,
                title=title,
                content=body.content,
                style=style,
                visibility=visibility,
                organization_id=organization_id,
                org_editable=body.org_editable if body.placement == 'org' else False,
            )
            return artifact_json(found, viewer, viewer.email)
        artifact_id = await mcp_server.create_artifact(
            viewer,
            title=title,
            content=content,
            type=artifact_type,  # pyright: ignore[reportArgumentType]
            theme=theme,  # pyright: ignore[reportArgumentType]  (a Theme or a value of DEFAULT_THEMES, kept in step by a test)
            visibility=visibility,
            org_editable=body.org_editable if body.placement == 'org' else False,
            organization_id=organization_id,
            styles=styles,
            style=style,
        )
    except (ToolError, build.BuildError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except workspace.ArtifactBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    found = await workspace.get_artifact(artifact_id)
    assert found is not None
    return artifact_json(found, viewer, viewer.email)


async def preset_for(preset_id: str, viewer: auth.Principal, kind: presets.Kind | None = None) -> workspace.Artifact:
    """A personal library entry; public visibility never grants access to someone else's library."""
    found = await artifact_for(preset_id, viewer)
    if found.workspace_id != viewer.workspace_id or found.preset_kind is None:
        raise HTTPException(404, 'library entry not found')
    if kind and found.preset_kind != kind:
        raise HTTPException(400, f'choose a saved {kind}')
    return found


@router.get('/presets')
async def list_presets(request: Request) -> dict[str, object]:
    """The signed-in user's reusable templates and styles."""
    viewer = await viewer_required(request)
    entries = await workspace.list_artifacts(viewer.workspace_id)
    return {
        'templates': [artifact_json(a, viewer) for a in entries if a.preset_kind == 'template'],
        'styles': [artifact_json(a, viewer) for a in entries if a.preset_kind == 'style'],
    }


class PresetBody(BaseModel):
    """Save a snapshot, or create a template starter or a style from CSS."""

    name: str
    kind: presets.Kind
    artifact_id: str | None = None
    type: mcp_server.ArtifactType = 'deck'
    theme: mcp_server.Theme | None = None
    css: str | None = None


@router.post('/presets', status_code=201)
async def save_preset(body: PresetBody, request: Request) -> dict[str, object]:
    """Save a reusable private entry without changing the source artifact."""
    mutation(request)
    viewer = await viewer_required(request)
    try:
        if body.artifact_id:
            if body.css is not None or body.theme is not None:
                raise HTTPException(400, 'a snapshot uses the source artifact styles and theme')
            source = await artifact_for(body.artifact_id, viewer)
            found = await presets.save(source, viewer.workspace_id, body.name, body.kind)
        else:
            if body.kind == 'style' and body.css is None:
                raise HTTPException(400, 'provide CSS or choose an existing artifact')
            found = await presets.create(
                viewer.workspace_id,
                body.name,
                'page' if body.kind == 'style' else body.type,
                kind=body.kind,
                css=body.css,
                theme=body.theme or agent.DEFAULT_THEMES['page' if body.kind == 'style' else body.type],
            )
    except build.BuildError as exc:
        raise HTTPException(400, str(exc)) from exc
    except workspace.ArtifactBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    return artifact_json(found, viewer, viewer.email)


@router.delete('/presets/{preset_id}', status_code=204)
async def remove_preset(preset_id: str, request: Request) -> Response:
    """Remove a library entry; its files and already-created artifacts are retained."""
    mutation(request)
    viewer = await viewer_required(request)
    await presets.remove(await preset_for(preset_id, viewer))
    return Response(status_code=204)


class StyleBody(BaseModel):
    style_id: str


@router.post('/artifacts/{artifact_id}/style')
async def apply_style(artifact_id: str, body: StyleBody, request: Request) -> dict[str, object]:
    """Replace appearance while preserving content and layout, in a validated commit."""
    mutation(request)
    viewer = await viewer_required(request)
    target = await artifact_for(artifact_id, viewer, edit=True)
    style = await preset_for(body.style_id, viewer, 'style')
    try:
        await presets.apply_style(target, style)
    except build.BuildError as exc:
        raise HTTPException(400, str(exc)) from exc
    except workspace.ArtifactBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    return artifact_json(await presets.saved(target.id), viewer)


class AccessBody(BaseModel):
    """Who may see and edit an artifact, and where it lives: `placement` left out keeps the current one."""

    public: bool
    org_editable: bool = False
    placement: Literal['personal', 'org'] | None = None


@router.patch('/artifacts/{artifact_id}')
async def set_access(artifact_id: str, body: AccessBody, request: Request) -> dict[str, object]:
    """Change who may see and edit an artifact, and move it between the owner's own space and their organisation;
    the owner only."""
    mutation(request)
    viewer = await viewer_required(request)
    found = await artifact_for(artifact_id, viewer, manage=True)
    if body.placement is None:
        organization_id = found.organization_id
    elif body.placement == 'org':
        if viewer.organization_id is None:
            raise HTTPException(400, 'your account is not in an organisation')
        organization_id = viewer.organization_id
    else:
        organization_id = None
    if organization_id is None:
        visibility = 'public' if body.public else 'private'
    else:
        visibility = 'public' if body.public else 'org'
    problem = access.check_access(visibility, body.org_editable, organization_id)
    if problem is not None:
        raise HTTPException(400, problem)
    changed = await workspace.set_access(
        found.id, visibility=visibility, org_editable=body.org_editable, organization_id=organization_id
    )
    return artifact_json(changed, viewer, viewer.email)


MAIN_MD = 'main.md'


@router.get('/artifacts/{artifact_id}/source')
async def get_source(artifact_id: str, request: Request) -> dict[str, object]:
    """The artifact's `main.md`, for the editor to start from; anyone who may see the page may read it."""
    viewer = await viewer_required(request)
    found = await artifact_for(artifact_id, viewer)
    async with workspace.open_artifact(found) as directory:
        path = markdown_source(directory)
        if not path.is_file():
            raise HTTPException(404, f'{MAIN_MD} not found')
        content = await asyncio.to_thread(path.read_text, encoding='utf-8')
    return {'content': content}


class SourceBody(BaseModel):
    content: str


def markdown_source(directory: Path) -> Path:
    """Resolve the editable source safely, even when unrelated build settings are temporarily invalid."""
    try:
        config_path = presets.contained(directory, directory / 'artifact.toml')
        raw = tomllib.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
        value = raw.get('markdown') or MAIN_MD
        if not isinstance(value, str) or Path(value).is_absolute():
            raise build.BuildError('markdown must be a relative path inside the artifact')
        return presets.contained(directory, directory / value)
    except (build.BuildError, tomllib.TOMLDecodeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put('/artifacts/{artifact_id}/source')
async def put_source(artifact_id: str, body: SourceBody, request: Request) -> dict[str, object]:
    """Replace `main.md` with what the editor holds, as one commit, then rebuild the page.

    The content is committed even when it does not build, as the agent's edits are: the editor is told the build
    error in `build_error` (with the checkout's path stripped from it) and keeps the user's work rather than losing
    it, and the stale page is removed so the preview shows the error rather than the last good build. An unchanged
    file makes no commit.
    """
    mutation(request)
    viewer = await viewer_required(request)
    found = await artifact_for(artifact_id, viewer, edit=True)
    try:
        async with workspace.edit(found.id, f'edit {MAIN_MD}') as tx:
            path = markdown_source(tx.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_text, body.content, encoding='utf-8')
    except workspace.ArtifactBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    build_error: str | None = None
    async with workspace.open_artifact(found) as directory:
        try:
            await asyncio.to_thread(
                build.build_html, directory, markdown_url=f'../{found.id}.md', css_validator=styles.validate
            )
        except build.BuildError as exc:
            build_error = str(exc).replace(f'{directory}/', '')
            (directory / 'dist' / 'index.html').unlink(missing_ok=True)
    return {'build_error': build_error}


def merge_turns(messages: list[UIMessage]) -> list[UIMessage]:
    """Fold consecutive assistant messages into one, as the live stream shows a turn.

    `dump_messages` makes one UI message per model response, so a turn with two tool calls and a reply is three
    assistant messages; `useChat` streams the same turn as one message with a `step-start` part between steps.
    Stored history should look like what the browser just saw.
    """
    merged: list[UIMessage] = []
    for message in messages:
        if merged and message.role == 'assistant' and merged[-1].role == 'assistant':
            previous = merged[-1]
            parts = [*previous.parts, StepStartUIPart(type='step-start'), *message.parts]
            merged[-1] = previous.model_copy(update={'parts': parts})
        else:
            merged.append(message)
    return merged


@router.get('/artifacts/{artifact_id}/chat')
async def get_chat(artifact_id: str, request: Request) -> dict[str, object]:
    """The viewer's conversation about this artifact, as the UI messages `useChat` starts from."""
    viewer = await viewer_required(request)
    found = await artifact_for(artifact_id, viewer)
    history, model = await chats.load(found.id, viewer.user_id)
    messages = merge_turns(VercelAIAdapter.dump_messages(history, sdk_version=7))
    return {
        'messages': UI_MESSAGES.dump_python(messages, by_alias=True, exclude_none=True, mode='json'),
        'model': model,
    }


@router.delete('/artifacts/{artifact_id}/chat', status_code=204)
async def clear_chat(artifact_id: str, request: Request) -> Response:
    """Forget the viewer's conversation about this artifact."""
    mutation(request)
    viewer = await viewer_required(request)
    found = await artifact_for(artifact_id, viewer, edit=True)
    await chats.clear(found.id, viewer.user_id)
    return Response(status_code=204)


async def name_after_first_turn(found: workspace.Artifact, model_id: str, result: AgentRunResult[Any]) -> None:
    """Replace the placeholder title with one the naming agent makes from the first request and the markdown it
    produced. Best effort: a model or storage failure is logged and the turn is unaffected."""
    request = next((p.content for m in result.all_messages() for p in m.parts if isinstance(p, UserPromptPart)), None)
    if not isinstance(request, str):
        return
    try:
        async with workspace.open_artifact(found) as directory:
            markdown = (directory / 'main.md').read_text(encoding='utf-8')
        title = await agent.suggest_title(agent.resolve_model(model_id), request, markdown)
        if title is not None:
            await workspace.rename_artifact(found.id, title)
    except Exception:
        logger.exception('naming artifact %s after its first turn failed', found.id)


@router.post('/artifacts/{artifact_id}/chat')
async def chat(artifact_id: str, request: Request) -> Response:
    """One turn of the editing conversation, streamed as Vercel AI SDK chunks.

    The body holds the new user message (the browser sends only that one) and `model`, the picker's choice. The
    agent runs with the stored history and the chosen model, acting as the viewer; when the turn completes the
    whole history is stored. The adapter accepts `application/json` only, a second lock against cross-site posts.
    """
    mutation(request)
    viewer = await viewer_required(request)
    found = await artifact_for(artifact_id, viewer, edit=True)
    adapter = await VercelAIAdapter[agent.ChatDeps, str].from_request(request, agent=agent.agent, sdk_version=7)
    extra: dict[str, Any] = adapter.run_input.__pydantic_extra__ or {}
    model_id = extra.get('model')
    # The page the preview shows, so the agent knows what "this slide" means; anything but a positive int is None.
    page = extra.get('page')
    page = page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None
    try:
        chosen = agent.check_model(model_id if isinstance(model_id, str) else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    history, _ = await chats.load(found.id, viewer.user_id)
    # The first turn of an artifact still carrying its placeholder title also names it, once the turn is stored.
    name_it = not history and agent.is_untitled(found.title)

    async def save(result: AgentRunResult[Any]) -> None:
        await chats.save(found.id, viewer.user_id, result.all_messages(), chosen)
        if name_it:
            await name_after_first_turn(found, chosen, result)

    async def events() -> AsyncIterator[BaseChunk]:
        # Set here, not around the call above: the body streams after this function has returned, in this task,
        # and the agent and its in-process MCP session run here too.
        token = auth.set_principal(viewer)
        try:
            async for event in adapter.run_stream(
                message_history=history,
                model=agent.resolve_model(chosen),
                deps=agent.ChatDeps(artifact=found, viewer=viewer, page=page),
                conversation_id=f'{found.id}:{viewer.user_id}',
                usage_limits=UsageLimits(request_limit=agent.REQUEST_LIMIT),
                on_complete=save,
            ):
                yield event
        finally:
            auth.reset_principal(token)

    return adapter.streaming_response(events())
