"""Exercise real subprocesses with a scripted CLI; no login, provider requests or database required."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import WebSearch
from pydantic_ai.exceptions import ModelAPIError, UserError
from pydantic_ai.messages import BinaryContent, ModelMessage, ModelRequest, TextPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

import agent
import cli_models
from cli_models import CLIModel


def test_model_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('OPENARTIFACT_MODELS', 'cli:codex=Codex CLI,cli:claude:sonnet=Claude Code,openai:test=API')
    assert [(m.id, m.name) for m in agent.configured_models()] == [
        ('cli:codex', 'Codex CLI'),
        ('cli:claude:sonnet', 'Claude Code'),
        ('openai:test', 'API'),
    ]
    assert agent.check_model(None) == 'cli:codex'
    codex = agent.resolve_model('cli:codex')
    assert isinstance(codex, CLIModel) and codex.cli_model is None
    claude = agent.resolve_model('cli:claude:sonnet')
    assert isinstance(claude, CLIModel) and claude.cli_model == 'sonnet'
    assert agent.resolve_model('openai:test') == 'openai:test'
    for invalid in ('cli:other', 'cli:codex:', 'cli:claude: '):
        with pytest.raises(ValueError, match='CLI model must be'):
            agent.resolve_model(invalid)


@pytest.mark.anyio
@pytest.mark.parametrize('backend', ['codex', 'claude'])
async def test_cli_tool_loop_history_and_streaming(backend: str, fake_cli: Callable[[str], Path]):
    capture = fake_cli(backend)
    model = CLIModel(f'cli:{backend}:chosen-model')
    editor = Agent(
        model, instructions='Edit the artifact with the declared tools.', capabilities=[WebSearch(max_uses=5)]
    )
    seen: list[int] = []

    @editor.tool_plain
    def double(number: int) -> int:
        seen.append(number)
        return number * 2

    async with editor.run_stream('Please double 21') as stream:
        assert await stream.get_output() == 'Done from the host CLI.'
    assert seen == [21]
    assert stream.usage.input_tokens == 160
    assert stream.usage.output_tokens == 20
    assert stream.usage.cache_read_tokens == 40
    second = await editor.run('Continue', message_history=stream.all_messages())
    assert second.output == 'Done from the host CLI.'
    recorded = json.loads(capture.read_text())
    assert '--model=chosen-model' in recorded['args']
    assert recorded['context']['instructions'] == 'Edit the artifact with the declared tools.'
    assert recorded['context']['web_search'][0]['max_uses'] == 5
    assert any(p.get('content') == ['Continue'] for m in recorded['context']['messages'] for p in m['parts'])
    result = next(p for m in recorded['context']['messages'] for p in m['parts'] if p['kind'] == 'tool-result')
    assert '42' in result['content'][0]
    assert not Path(recorded['cwd']).exists(), 'temporary context must be removed'
    if backend == 'codex':
        assert '--ephemeral' in recorded['args'] and '--ignore-user-config' in recorded['args']
        assert 'read-only' in recorded['args'] and 'shell_tool' in recorded['args']
    else:
        assert '--no-session-persistence' in recorded['args'] and '--safe-mode' in recorded['args']
        assert recorded['args'][recorded['args'].index('--tools') + 1] == 'WebSearch'
        assert '--strict-mcp-config' in recorded['args']


@pytest.mark.anyio
@pytest.mark.parametrize('backend', ['codex', 'claude'])
async def test_media_in_user_and_screenshot_results(backend: str, fake_cli: Callable[[str], Path]):
    capture = fake_cli(backend)
    picture = BinaryContent(b'image fixture', media_type='image/png')
    messages: list[ModelMessage] = [
        ModelRequest(
            parts=[
                UserPromptPart(['See reference', picture]),
                ToolReturnPart('screenshot', [picture], tool_call_id='shot'),
            ]
        )
    ]
    response = await CLIModel(f'cli:{backend}').request(messages, None, ModelRequestParameters())
    assert isinstance(response.parts[0], TextPart)
    recorded = json.loads(capture.read_text())
    assert recorded['media'] == [picture.data.hex(), picture.data.hex()]
    parts = recorded['context']['messages'][0]['parts']
    assert parts[0]['content'][1]['attachment'] == 1
    assert parts[1]['content'][-2]['attachment'] == 2
    assert not Path(recorded['cwd']).exists()


@pytest.mark.anyio
async def test_pdf_capability_is_explicit(fake_cli: Callable[[str], Path]):
    capture = fake_cli('claude')
    fake_cli('codex')
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart([BinaryContent(b'pdf fixture', media_type='application/pdf')])])
    ]
    await CLIModel('cli:claude').request(messages, None, ModelRequestParameters())
    assert json.loads(capture.read_text())['media'] == [b'pdf fixture'.hex()]
    with pytest.raises(UserError, match='Codex CLI accepts image references'):
        await CLIModel('cli:codex').request(messages, None, ModelRequestParameters())


@pytest.mark.anyio
@pytest.mark.parametrize('mode,match', [('fail', 'status 7'), ('invalid', 'invalid reply'), ('flood', 'exceeded 4 MB')])
async def test_cli_errors_are_bounded_and_private(
    mode: str, match: str, fake_cli: Callable[[str], Path], monkeypatch: pytest.MonkeyPatch
):
    capture = fake_cli('codex')
    monkeypatch.setenv('CLI_TEST_MODE', mode)
    with pytest.raises(ModelAPIError, match=match) as caught:
        await Agent(CLIModel('cli:codex')).run('private user input')
    assert 'private' not in str(caught.value)
    assert not Path(json.loads(capture.read_text())['cwd']).exists()


@pytest.mark.anyio
async def test_missing_cli_is_informative(monkeypatch: pytest.MonkeyPatch):
    def missing(command: str) -> None:
        return None

    monkeypatch.setattr(shutil, 'which', missing)
    with pytest.raises(UserError, match='not on the OpenArtifact host PATH'):
        await Agent(CLIModel('cli:claude')).run('hello')


@pytest.mark.parametrize(
    'backend,output',
    [
        ('codex', b'{"type":"turn.failed"}'),
        ('codex', b'{"type":"turn.completed"}'),
        ('claude', b'{"type":"result","subtype":"error_during_execution","is_error":true}'),
        ('claude', b'{"type":"result","subtype":"success"}'),
    ],
)
def test_failed_or_incomplete_protocol(backend: str, output: bytes):
    with pytest.raises(ModelAPIError, match='invalid reply'):
        CLIModel(f'cli:{backend}').response(output)


@pytest.mark.anyio
@pytest.mark.parametrize('cancel', [False, True])
async def test_timeout_and_cancellation_kill_process_group(tmp_path: Path, cancel: bool):
    marker = tmp_path / 'started'
    script = "import pathlib, subprocess, sys, time\nchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\npathlib.Path(sys.argv[1]).write_text(str(child.pid))\ntime.sleep(30)"
    task = asyncio.create_task(
        cli_models.run_process(
            [sys.executable, '-c', script, str(marker)], b'', tmp_path, timeout=30 if cancel else 0.5, backend='codex'
        )
    )
    async with asyncio.timeout(5):
        while not marker.exists():
            await asyncio.sleep(0.01)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ModelAPIError, match='request timeout'):
            await task
    pid = int(marker.read_text())
    # The OS can briefly retain a killed orphan as a zombie; ps distinguishes it from a running child.
    check = await asyncio.create_subprocess_exec('ps', '-o', 'stat=', '-p', str(pid), stdout=asyncio.subprocess.PIPE)
    stdout, _ = await check.communicate()
    assert not stdout.strip() or stdout.strip().startswith(b'Z')
