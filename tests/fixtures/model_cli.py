"""A deterministic stand-in for both CLIs. No provider, credentials or external service is contacted."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

args = sys.argv[1:]
backend = Path(sys.argv[0]).name
raw = sys.stdin.read()
if backend == 'claude':
    blocks = json.loads(raw)['message']['content']
    prompt = blocks[0]['text']
    media = [base64.b64decode(block['source']['data']) for block in blocks[1:]]
else:
    prompt = raw
    media = [Path(args[i + 1]).read_bytes() for i, arg in enumerate(args) if arg == '--image']
context = json.loads('{' + prompt.split('\n{', 1)[1])
capture = os.environ.get('CLI_TEST_CAPTURE')
if capture:
    Path(capture).write_text(
        json.dumps({'args': args, 'cwd': os.getcwd(), 'context': context, 'media': [item.hex() for item in media]})
    )

mode = os.environ.get('CLI_TEST_MODE', 'edit')
if mode == 'fail':
    print('private prompt and credentials must not reach the client', file=sys.stderr)
    sys.exit(7)
if mode == 'invalid':
    print('private invalid provider output')
    sys.exit(0)
if mode == 'flood':
    sys.stdout.write('x' * (5 * 1024 * 1024))
    sys.exit(0)

parts = [part for message in context['messages'] for part in message['parts']]
returns = [part for part in parts if part['kind'] == 'tool-result']
tools = {tool['name'] for tool in context['tools']}
calls = []
text = 'Done from the host CLI.'
if tools and not returns:
    if 'run_code' in tools:
        artifact = re.search(r'`([0-9a-f-]{36})`', context['instructions'])
        assert artifact
        name = 'run_code'
        arguments = {
            'artifact': artifact[1],
            'code': "from pathlib import Path\nPath('main.md').write_text('# CLI edit\\n')",
        }
    else:
        name = 'double'
        arguments = {'number': 21}
    calls = [{'name': name, 'arguments': json.dumps(arguments)}]
    text = ''
elif 'build' in tools and len(returns) == 1:
    artifact = re.search(r'`([0-9a-f-]{36})`', context['instructions'])
    assert artifact
    calls = [{'name': 'build', 'arguments': json.dumps({'artifact': artifact[1]})}]
    text = ''
reply = {'text': text, 'tool_calls': calls}
if backend == 'codex':
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Working...'}}))
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(reply)}}))
    print(
        json.dumps(
            {'type': 'turn.completed', 'usage': {'input_tokens': 80, 'output_tokens': 10, 'cached_input_tokens': 20}}
        )
    )
else:
    print(json.dumps({'type': 'system', 'subtype': 'init'}))
    print(
        json.dumps(
            {
                'type': 'result',
                'subtype': 'success',
                'is_error': False,
                'structured_output': reply,
                'usage': {
                    'input_tokens': 50,
                    'cache_read_input_tokens': 20,
                    'cache_creation_input_tokens': 10,
                    'output_tokens': 10,
                    'server_tool_use': {'web_search_requests': 0},
                },
            }
        )
    )
