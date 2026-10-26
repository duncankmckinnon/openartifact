"""Tests for `backend/api.py`: the JSON API behind the web app, and the app shell routes in `server.py`."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

import presets
import pytest
from conftest import DEV_TOKEN
from fastapi.testclient import TestClient
from test_server import in_app, org_members, seed_starter, sign_in, sign_out, starter, stub_chrome

import config
import server
import workspace


@pytest.fixture
def client(server_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    shell = tmp_path / 'index.html'
    shell.write_text('<!doctype html><title>app</title><div id="root"></div>')
    monkeypatch.setattr(server, 'APP_INDEX', shell)
    with TestClient(server.app) as client:
        yield client


def test_shell_requires_sign_in(client: TestClient):
    for path in ('/', '/edit/abc'):
        anonymous = client.get(path, headers={'accept': 'text/html'}, follow_redirects=False)
        assert anonymous.status_code == 303 and anonymous.headers['location'].startswith('/login?next=')
    artifact = starter(client)
    for path in ('/', f'/edit/{artifact.id}'):
        page = client.get(path)
        assert page.status_code == 200 and 'id="root"' in page.text
        assert page.headers['cache-control'] == 'no-store'


def test_api_requires_sign_in(client: TestClient):
    assert client.get('/api/').status_code == 200
    for path in ('/api/me', '/api/configure', '/api/artifacts'):
        response = client.get(path)
        assert response.status_code == 401 and response.json() == {'detail': 'sign in required'}, path
    assert client.post('/api/artifacts', json={'title': 'x'}).status_code == 401


def test_personal_library_workflow(client: TestClient):
    original = starter(client)
    template = client.post(
        '/api/presets', json={'artifact_id': str(original.id), 'name': 'My deck', 'kind': 'template'}
    )
    assert template.status_code == 201, template.text
    template = template.json()
    assert template['preset_kind'] == 'template'
    style = client.post('/api/presets', json={'name': 'Purple', 'kind': 'style', 'css': ':root {--accent: purple}'})
    assert style.status_code == 201, style.text
    style = style.json()
    assert client.post(f'/api/drafts/{style["id"]}/save', json={'name': 'Purple'}).status_code == 200
    entries = client.get('/api/presets').json()
    assert [a['id'] for a in entries['templates']] == [template['id']]
    assert [a['id'] for a in entries['styles']] == [style['id']]
    created = client.post(
        '/api/artifacts', json={'template_id': template['id'], 'style_id': style['id'], 'title': 'Copy'}
    )
    assert created.status_code == 201, created.text
    created = created.json()
    assert (created['type'], created['title'], created['preset_kind']) == ('deck', 'Copy', None)
    applied = client.post(f'/api/artifacts/{original.id}/style', json={'style_id': style['id']})
    assert applied.status_code == 200, applied.text
    assert 'purple' in client.get(f'/artifacts/{original.id}/styles.css').text
    assert client.delete(f'/api/presets/{template["id"]}').status_code == 204
    assert client.get('/api/presets').json()['templates'] == []
    assert client.get(f'/artifacts/{template["id"]}/').status_code == 200


def test_library_permissions_and_invalid_inputs(client: TestClient):
    original = starter(client)
    colleague, outsider = org_members(client)
    style = client.post('/api/presets', json={'name': 'Brand', 'kind': 'style', 'css': 'p {color:red}'}).json()
    assert client.post(f'/api/drafts/{style["id"]}/save', json={'name': 'Brand'}).status_code == 200
    assert client.post('/api/artifacts', json={'template_id': style['id']}).status_code == 400
    assert client.post('/api/presets', json={'name': ' ', 'kind': 'template'}).status_code == 400
    assert client.post('/api/presets', json={'name': 'Bad', 'kind': 'style', 'css': '</style>'}).status_code == 400
    assert client.post('/api/presets', json={'name': 'Blank', 'kind': 'style'}).status_code == 201
    assert client.post('/api/presets', json={'name': 'Bad', 'kind': 'other'}).status_code == 422
    cross = {'sec-fetch-site': 'cross-site'}
    assert client.post('/api/presets', json={'name': 'Cross', 'kind': 'template'}, headers=cross).status_code == 403
    assert client.delete(f'/api/presets/{style["id"]}', headers=cross).status_code == 403
    client.patch(f'/api/artifacts/{style["id"]}', json={'public': True})
    client.patch(f'/api/artifacts/{original.id}', json={'placement': 'org', 'public': False})
    sign_in(client, colleague)
    assert client.get('/api/presets').json() == {'templates': [], 'styles': []}
    assert client.post('/api/artifacts', json={'style_id': style['id']}).status_code == 404
    assert client.delete(f'/api/presets/{style["id"]}').status_code == 404
    assert client.post(f'/api/artifacts/{original.id}/style', json={'style_id': style['id']}).status_code == 403
    saved = client.post('/api/presets', json={'artifact_id': str(original.id), 'name': 'Team copy', 'kind': 'template'})
    assert saved.status_code == 201
    sign_in(client, outsider)
    assert (
        client.post(
            '/api/presets', json={'artifact_id': str(original.id), 'name': 'Hidden', 'kind': 'template'}
        ).status_code
        == 404
    )
    sign_out(client)
    assert client.get('/api/presets').status_code == 401


def test_create_template_for_description_workflow(client: TestClient):
    starter(client)
    response = client.post('/api/presets', json={'name': 'Board report', 'kind': 'template', 'type': 'document'})
    assert response.status_code == 201, response.text
    template = response.json()
    assert (template['type'], template['preset_kind'], template['visibility']) == ('document', 'template', 'private')
    assert client.get(f'/artifacts/{template["id"]}/').status_code == 200


def test_draft_lifecycle_and_permissions(client: TestClient):
    starter(client)
    owner, _ = in_app(client, seed_starter)
    colleague, _ = org_members(client)
    draft = client.post('/api/presets', json={'name': 'Report', 'kind': 'template', 'type': 'document'}).json()
    ident = draft['id']
    assert draft['draft'] and draft['version']
    assert ident not in {a['id'] for a in client.get('/api/artifacts').json()['mine']}
    assert client.get('/api/presets').json()['templates'] == []
    assert client.patch(f'/api/artifacts/{ident}', json={'public': True}).status_code == 400
    assert client.post('/api/artifacts', json={'template_id': ident}).status_code == 404
    for route in ('save', 'discard'):
        assert (
            client.post(
                f'/api/drafts/{ident}/{route}', json={'name': 'Report'}, headers={'sec-fetch-site': 'cross-site'}
            ).status_code
            == 403
        )
    sign_in(client, colleague)
    assert client.post(f'/api/drafts/{ident}/save', json={'name': 'Other'}).status_code == 404
    assert client.post(f'/api/drafts/{ident}/discard').status_code == 404
    sign_in(client, owner)
    client.put(f'/api/artifacts/{ident}/source', json={'content': '# {{ UNKNOWN }}\n'})
    broken = client.post(f'/api/drafts/{ident}/save', json={'name': 'Board report'})
    assert broken.status_code == 400 and 'UNKNOWN' in broken.json()['detail']
    assert str(workspace.checkout_path(uuid.UUID(ident))) not in broken.text
    client.put(f'/api/artifacts/{ident}/source', json={'content': '# Report\n'})
    saved = client.post(f'/api/drafts/{ident}/save', json={'name': 'Board report'})
    assert saved.status_code == 200 and not saved.json()['draft']
    assert client.get('/api/presets').json()['templates'][0]['title'] == 'Board report'
    other = client.post('/api/presets', json={'name': 'Discard', 'kind': 'style'}).json()
    assert client.post(f'/api/drafts/{other["id"]}/discard').status_code == 204
    assert client.get(f'/api/artifacts/{other["id"]}/source').status_code == 404


def test_saved_entry_thumbnails_are_cached_per_version(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    original = starter(client)
    entry = client.post(
        '/api/presets', json={'artifact_id': str(original.id), 'kind': 'template', 'name': 'Thumb'}
    ).json()
    asked = stub_chrome(monkeypatch, 200, b'png')
    url = f'/api/presets/{entry["id"]}/thumbnail?v={entry["version"]}'
    for _ in range(2):
        response = client.get(url)
        assert response.status_code == 200 and response.content == b'png'
        assert response.headers['cache-control'] == 'private, max-age=86400'
    assert len(asked) == 1 and asked[0].endswith(' 1600x900')
    client.put(f'/api/artifacts/{entry["id"]}/source', json={'content': '# New version\n'})
    assert client.get(url).status_code == 409
    updated = client.get(f'/api/artifacts/{entry["id"]}').json()
    assert client.get(f'/api/presets/{entry["id"]}/thumbnail?v={updated["version"]}').status_code == 200
    assert len(asked) == 2


def test_style_thumbnail_is_a_saved_guide_or_a_service_error(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    starter(client)
    entry = client.post('/api/presets', json={'kind': 'style', 'name': 'Thumb'}).json()
    url = f'/api/presets/{entry["id"]}/thumbnail'
    assert client.get(url).status_code == 404
    client.post(f'/api/drafts/{entry["id"]}/save', json={'name': 'Thumb'})
    monkeypatch.delenv('OPENARTIFACT_CHROME_URL', raising=False)
    assert client.get(url).status_code == 503
    asked = stub_chrome(monkeypatch, 200, b'png')
    assert client.get(url).status_code == 200
    assert '?guide&type=document' in asked[0] and asked[0].endswith(' 800x450')


def test_lifespan_starts_and_stops_draft_sweeper(server_env: None, monkeypatch: pytest.MonkeyPatch):
    ran = threading.Event()

    async def sweep() -> int:
        ran.set()
        return 0

    monkeypatch.setattr(presets, 'sweep_drafts', sweep)
    monkeypatch.setattr(presets, 'SWEEP_INTERVAL', 0.01)
    with TestClient(server.app):
        assert ran.wait(2)


def test_source_edit_survives_invalid_config_and_respects_custom_paths(client: TestClient):
    artifact = starter(client)

    async def break_config() -> None:
        async with workspace.edit(artifact.id, 'invalid config') as tx:
            (tx.path / 'artifact.toml').write_text('theme = "typo"\nmarkdown = "notes.md"\n')
            (tx.path / 'notes.md').write_text('# Custom source\n')

    in_app(client, break_config)
    read = client.get(f'/api/artifacts/{artifact.id}/source')
    assert read.status_code == 200, read.text
    assert read.json()['content'] == '# Custom source\n'
    response = client.put(f'/api/artifacts/{artifact.id}/source', json={'content': '# Keep my edits\n'})
    assert response.status_code == 200, response.text
    assert 'invalid theme' in response.json()['build_error']
    assert (workspace.checkout_path(artifact.id) / 'notes.md').read_text() == '# Keep my edits\n'


def test_new_artifact_with_a_saved_style_and_on_demand_css_validation(client: TestClient):
    starter(client)
    style = client.post('/api/presets', json={'name': 'Blue', 'kind': 'style', 'css': 'p {color: blue}'}).json()
    assert client.post(f'/api/drafts/{style["id"]}/save', json={'name': 'Blue'}).status_code == 200
    response = client.post('/api/artifacts', json={'type': 'page', 'style_id': style['id']})
    assert response.status_code == 201, response.text
    artifact = response.json()
    assert client.get(f'/artifacts/{artifact["id"]}/').status_code == 200

    async def missing_css_asset() -> None:
        async with workspace.edit(uuid.UUID(artifact['id']), 'responsive CSS with missing asset') as tx:
            (tx.path / 'styles.css').write_text('p {background: image-set("missing.svg" 1x)}')
            (tx.path / 'dist/index.html').unlink(missing_ok=True)

    in_app(client, missing_css_asset)
    page = client.get(f'/artifacts/{artifact["id"]}/')
    assert page.status_code == 422, page.text
    assert 'CSS asset not found' in page.text


def test_me_and_configure(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    artifact = starter(client)
    colleague, _ = org_members(client)
    me = client.get('/api/me').json()
    assert me['viewer']['email'] == 'seed@x.test' and me['organization'] == {'domain': 'x.test', 'name': 'x.test'}
    sign_in(client, colleague)
    assert client.get('/api/me').json()['viewer']['name'] == 'C'
    monkeypatch.setenv('OPENARTIFACT_MODELS', 'gateway/anthropic:claude-opus-5-5=Opus, test:x = Test X')
    assert client.get('/api/configure').json() == {
        'mcp': {'url': f'{config.base_url()}/mcp/', 'auth': 'token', 'token': DEV_TOKEN},
        'models': [{'id': 'gateway/anthropic:claude-opus-5-5', 'name': 'Opus'}, {'id': 'test:x', 'name': 'Test X'}],
        'default': 'gateway/anthropic:claude-opus-5-5',
    }
    # With Google login configured the clients sign in themselves: no token to show.
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'client-id')
    assert client.get('/api/configure').json()['mcp'] == {
        'url': f'{config.base_url()}/mcp/',
        'auth': 'oauth',
        'token': None,
    }
    monkeypatch.delenv('GOOGLE_CLIENT_ID')
    monkeypatch.setenv('OPENARTIFACT_MODELS', 'test:x=Test X')
    assert client.get('/api/configure').json()['default'] == 'test:x'
    monkeypatch.delenv('OPENARTIFACT_MODELS')
    monkeypatch.delenv('PYDANTIC_AI_GATEWAY_API_KEY', raising=False)
    unconfigured = client.get('/api/configure').json()
    assert (unconfigured['models'], unconfigured['default']) == ([], None)
    monkeypatch.setenv('PYDANTIC_AI_GATEWAY_API_KEY', 'pylf_v1_eu_test')
    configured = client.get('/api/configure').json()
    assert configured['default'] == 'gateway/anthropic:claude-opus-5-5'
    assert [m['id'] for m in configured['models']] == [
        'gateway/anthropic:claude-opus-5-5',
        'gateway/anthropic:claude-sonnet-5-5',
        'gateway/openai:gpt-6-astra',
        'gateway/openai:gpt-6.1-sol',
        'gateway/openai:gpt-6-luna',
    ]
    assert artifact.id


def test_create_with_defaults_and_move_between_spaces(client: TestClient):
    starter(client)
    colleague, _ = org_members(client)
    # One click, one field: the type. Title, theme and content follow from it.
    created = client.post('/api/artifacts', json={'type': 'document'})
    assert created.status_code == 201, created.text
    doc = created.json()
    assert (doc['title'], doc['type'], doc['visibility'], doc['org_editable']) == (
        'Untitled document',
        'document',
        'private',
        False,
    )
    directory = workspace.checkout_path(uuid.UUID(doc['id']))
    assert (directory / 'main.md').read_text().startswith('# Your document\n')
    assert 'theme = "light"' in (directory / 'artifact.toml').read_text()
    assert (directory / 'styles.css').read_text().startswith(':root {')
    deck = client.post('/api/artifacts', json={'type': 'deck'}).json()
    assert deck['title'] == 'Untitled deck'
    assert 'theme = "dark"' in (workspace.checkout_path(uuid.UUID(deck['id'])) / 'artifact.toml').read_text()
    # The owner moves it into the organisation and back; a colleague sees it only while it is there.
    moved = client.patch(
        f'/api/artifacts/{doc["id"]}', json={'placement': 'org', 'public': False, 'org_editable': True}
    )
    assert moved.status_code == 200, moved.text
    assert (moved.json()['visibility'], moved.json()['org_editable']) == ('org', True)
    sign_in(client, colleague)
    assert [a['id'] for a in client.get('/api/artifacts').json()['shared']] == [doc['id']]
    sign_in(client, in_app(client, seed_starter)[0])
    back = client.patch(f'/api/artifacts/{doc["id"]}', json={'placement': 'personal', 'public': False}).json()
    assert (back['visibility'], back['org_editable']) == ('private', False)
    sign_in(client, colleague)
    assert client.get('/api/artifacts').json()['shared'] == []
    # Nobody without an organisation can place an artifact in one.
    assert client.patch(f'/api/artifacts/{doc["id"]}', json={'placement': 'org', 'public': True}).status_code == 404


def test_list_create_and_access(client: TestClient):
    artifact = starter(client)
    colleague, outsider = org_members(client)
    listed = client.get('/api/artifacts').json()
    assert [a['id'] for a in listed['mine']] == [str(artifact.id)] and listed['shared'] == []
    mine = listed['mine'][0]
    assert (mine['visibility'], mine['can_edit'], mine['can_manage'], mine['owner_email']) == (
        'private',
        True,
        True,
        'seed@x.test',
    )
    assert mine['url'].endswith(f'/artifacts/{artifact.id}/')

    # Create: a personal public page, then an org one editable by the org; bad combinations are 400.
    created = client.post('/api/artifacts', json={'title': ' Notes ', 'type': 'page', 'public': True})
    assert created.status_code == 201, created.text
    notes = created.json()
    assert (notes['title'], notes['type'], notes['visibility']) == ('Notes', 'page', 'public')
    page = client.get(f'/artifacts/{notes["id"]}/main.md')
    assert page.text.startswith('# Your page\n')  # the type's starter content, with no content given
    assert client.get(f'/artifacts/{notes["id"]}/styles.css').status_code == 200
    team = client.post(
        '/api/artifacts',
        json={'title': 'Team', 'placement': 'org', 'org_editable': True, 'content': '# Team\n\nHello.\n'},
    ).json()
    assert (team['visibility'], team['org_editable']) == ('org', True)
    # A blank title is the placeholder, like no title at all; the type is checked.
    assert client.post('/api/artifacts', json={'title': '  '}).json()['title'] == 'Untitled deck'
    assert client.post('/api/artifacts', json={'title': 'T', 'type': 'scroll'}).status_code == 422
    cross = client.post('/api/artifacts', json={'title': 'T'}, headers={'sec-fetch-site': 'cross-site'})
    assert cross.status_code == 403

    # The colleague sees the org artifact as shared, with the owner's email; the outsider sees only the public one.
    sign_in(client, colleague)
    listed = client.get('/api/artifacts').json()
    assert listed['mine'] == []
    assert [(a['title'], a['owner_email'], a['can_edit']) for a in listed['shared']] == [('Team', 'seed@x.test', True)]
    sign_in(client, outsider)
    assert client.get('/api/artifacts').json() == {'mine': [], 'shared': []}
    assert client.post('/api/artifacts', json={'title': 'T', 'placement': 'org'}).status_code == 400

    # Access changes: owner only, validated.
    sign_in(client, colleague)
    assert client.patch(f'/api/artifacts/{team["id"]}', json={'public': True}).status_code == 403
    assert client.patch(f'/api/artifacts/{artifact.id}', json={'public': True}).status_code == 404
    sign_out(client)
    seed, _ = in_app(client, seed_starter)
    sign_in(client, seed)
    changed = client.patch(f'/api/artifacts/{team["id"]}', json={'public': True, 'org_editable': False}).json()
    assert (changed['visibility'], changed['org_editable']) == ('public', False)
    bad = client.patch(f'/api/artifacts/{notes["id"]}', json={'public': False, 'org_editable': True})
    assert bad.status_code == 400 and 'personal artifact' in bad.json()['detail']
    row = in_app(client, lambda: workspace.get_artifact(workspace.uuid.UUID(team['id'])))
    assert row is not None and row.visibility == 'public'


def test_source_read_and_save(client: TestClient):
    artifact = starter(client)
    colleague, _ = org_members(client)
    original = (Path(__file__).parent.parent / 'examples' / 'starter' / 'main.md').read_text(encoding='utf-8')
    assert client.get(f'/api/artifacts/{artifact.id}/source').json() == {'content': original}

    # A save is one commit, rebuilt on the spot, and the page and the source route show it.
    saved = client.put(f'/api/artifacts/{artifact.id}/source', json={'content': '# Edited\n\nBy hand.\n'})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {'build_error': None}
    assert client.get(f'/artifacts/{artifact.id}/main.md').text == '# Edited\n\nBy hand.\n'
    assert client.get(f'/api/artifacts/{artifact.id}/source').json() == {'content': '# Edited\n\nBy hand.\n'}
    assert 'By hand.' in client.get(f'/artifacts/{artifact.id}/').text
    log = in_app(client, lambda: workspace.artifact_git(artifact.id, 'log', '--format=%s'))
    assert log.splitlines()[0] == 'edit main.md'

    # Content that does not build is kept, and the error reported, so nothing typed is lost.
    broken = client.put(f'/api/artifacts/{artifact.id}/source', json={'content': '# One\n---\n# Two\n'})
    assert broken.status_code == 200
    error = broken.json()['build_error']
    assert error.startswith('main.md:2: put a blank line before ---'), error
    assert client.get(f'/api/artifacts/{artifact.id}/source').json()['content'] == '# One\n---\n# Two\n'
    assert client.get(f'/artifacts/{artifact.id}/').status_code == 422

    # Guards: cross-site, not signed in, and a colleague without edit rights (the artifact is private: 404).
    cross = client.put(
        f'/api/artifacts/{artifact.id}/source', json={'content': 'x'}, headers={'sec-fetch-site': 'cross-site'}
    )
    assert cross.status_code == 403
    sign_in(client, colleague)
    assert client.get(f'/api/artifacts/{artifact.id}/source').status_code == 404
    assert client.put(f'/api/artifacts/{artifact.id}/source', json={'content': 'x'}).status_code == 404
    sign_out(client)
    assert client.get(f'/api/artifacts/{artifact.id}/source').status_code == 401
    assert client.put(f'/api/artifacts/{artifact.id}/source', json={'content': 'x'}).status_code == 401
