"""Measure synthetic style specimens in real Chrome, without model or reference-provider requests."""

from __future__ import annotations

import functools
import subprocess
import threading
from collections.abc import Iterator
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import build
from chrome import pdf

RUNTIME = Path(__file__).resolve().parent.parent / 'frontend/dist/openartifact.js'
pytestmark = pytest.mark.skipif(
    pdf.find_chrome() is None or not RUNTIME.exists(), reason='Chrome and built runtime required'
)


class Guide(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.levels: dict[str, dict[str, str | None]] = {}
        self.colors: dict[str, str | None] = {}
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == 'tr' and (level := values.get('data-level')):
            self.levels[level] = values
        if tag == 'div' and (token := values.get('data-token')):
            self.colors[token] = values.get('data-value')


@pytest.fixture
def guide_url(tmp_path: Path) -> Iterator[str]:
    directory = tmp_path / 'a'
    directory.mkdir()
    (directory / 'artifact.toml').write_text('title = "Synthetic style"\ntype = "page"\ntheme = "light"\n')
    (directory / 'main.md').write_text('# Preview\n')
    (directory / 'styles.css').write_text(
        ':root{--accent:#ff6b4a}.artifact-document .prose h1{font-size:30px;line-height:36px;font-weight:600}.page.cover{--slide-heading:#112233}'
    )
    (directory / 'index.html').write_bytes(build.build_html(directory).read_bytes())
    (tmp_path / 'openartifact.js').write_bytes(RUNTIME.read_bytes())
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/a/'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('kind', ['deck', 'document', 'page'])
def test_guide_measures_type_scoped_sizes_and_colors(guide_url: str, kind: str):
    dumped = pdf.dump_dom(f'{guide_url}?guide&type={kind}')
    guide = Guide(dumped.html)
    assert set(guide.levels) == {'Title', 'Heading 1', 'Heading 2', 'Heading 3', 'Body', 'Small', 'Code'}
    heading = guide.levels['Heading 1']
    if kind == 'document':
        assert heading['data-size'] == '30px'
        assert heading['data-line-height'] == '36px'
        assert heading['data-weight'] == '600'
    else:
        assert heading['data-size'] != '30px'
    assert guide.colors['--accent'] == '#ff6b4a'
    assert 'rgb(17, 34, 51)' in dumped.html  # Cover sample keeps its resolved heading colour.


def test_guide_without_css(guide_url: str, tmp_path: Path):
    directory = tmp_path / 'a'
    (directory / 'styles.css').write_text('')
    (directory / 'index.html').write_bytes(build.build_html(directory).read_bytes())
    guide = Guide(pdf.dump_dom(f'{guide_url}?guide&type=page').html)
    assert len(guide.levels) == 7 and guide.colors


def test_local_font_loads_and_responsive_rules_are_measured(guide_url: str, tmp_path: Path):
    directory = tmp_path / 'a'
    (directory / 'test.woff2').write_bytes((Path(__file__).parent / 'fixtures/guide-test.woff2').read_bytes())
    (directory / 'styles.css').write_text(
        '@font-face{font-family:"Guide Test";src:url(test.woff2) format("woff2")} :root{--font-heading:"Guide Test",serif} .artifact-document .prose{--accent:#123456} @media(min-width:1px){.artifact-document .prose h2{font-size:27px}}'
    )
    html = build.build_html(directory).read_text()
    html += """<script>addEventListener('load', () => document.fonts.ready.then(() => {
      document.documentElement.dataset.fontReady = String(Array.from(document.fonts).some(f => f.family === 'Guide Test' && f.status === 'loaded'));
    }));</script>"""
    (directory / 'index.html').write_text(html)
    chrome = pdf.find_chrome()
    assert chrome is not None
    dumped = subprocess.run(
        [
            chrome,
            '--headless=new',
            '--disable-gpu',
            *pdf.container_flags(),
            '--virtual-time-budget=2000',
            '--dump-dom',
            f'{guide_url}?guide&type=document',
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    assert 'data-font-ready="true"' in dumped
    assert 'data-family="Guide Test"' in dumped
    guide = Guide(dumped)
    assert guide.levels['Heading 2']['data-size'] == '27px'
    assert guide.colors['--accent'] == '#123456'
