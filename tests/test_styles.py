"""Parser-backed CSS resource handling preserves valid CSS and bounds untrusted input."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import styles
from tinycss2 import ast

import build


def test_parse_handles_escaped_names_and_image_set_candidates():
    css = r"""/* url("old.svg") */
@media print {
  .page {background-image: image-set("assets/one.svg" type("image/svg+xml") 1x, u\72l("assets/two.svg") 2x)}
  .page::after {content: "url(sample.svg) @import"}
}"""
    assert styles.parse(css).urls == ['assets/one.svg', 'assets/two.svg']
    assert styles.parse('p {background: image-set(url(first.svg) 1x, "second.svg" 2x)}').urls == [
        'first.svg',
        'second.svg',
    ]


def test_rewrite_serializes_quotes_spaces_and_url_suffixes():
    css = """.page {background: image-set("assets/logo (1).svg?v=1#mark" 1x, url("assets/it's.svg") 2x)}"""
    rewritten = styles.parse(css).rewrite(lambda url: 'copied/' + quote(url, safe='/?=#'))
    assert styles.parse(rewritten).urls == ['copied/assets/logo%20%281%29.svg?v=1#mark', 'copied/assets/it%27s.svg']


@pytest.mark.parametrize(
    ('css', 'value'),
    [
        (r'.page::after {content: "\3c /style>"}', '</style>'),
        (r'.page {background: url(https://example.invalid/\3c /style>)}', 'https://example.invalid/</style>'),
    ],
)
def test_rewrite_keeps_strings_safe_for_html_embedding(css: str, value: str):
    css += ' @media (width < 600px) {p {color: red}}'
    rewritten = styles.parse(css).rewrite(lambda url: url)
    build.check_styles(rewritten, Path('styles.css'))
    assert '(width < 600px)' in rewritten
    work = list(styles.parse(rewritten).rules)
    values: list[str] = []
    while work:
        node = work.pop()
        if isinstance(node, (ast.StringToken, ast.URLToken)):
            values.append(node.value)
        work.extend(styles.children(node))
    assert value in values


@pytest.mark.parametrize(
    'css', ['@import "theme.css";', r'@\69mport "theme.css";', '@media print {@import url(theme.css);}']
)
def test_saved_styles_reject_imports_after_decoding(css: str):
    with pytest.raises(build.BuildError, match='import'):
        styles.parse(css)


@pytest.mark.parametrize('css', ['p {content: "unterminated}', 'p {color: red; ]'])
def test_malformed_css_fails_clearly(css: str):
    with pytest.raises(build.BuildError, match='CSS'):
        styles.parse(css)


def test_unterminated_comments_finish_in_a_bounded_subprocess():
    result = subprocess.run(
        [sys.executable, '-c', "import styles; assert styles.parse('/*x' * 160000).urls == []"],
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parent.parent / 'backend')},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_input_limits_apply_before_parsing_nested_or_large_css():
    with pytest.raises(build.BuildError, match='size|large'):
        styles.parse('/*' + 'a' * 1_000_000 + '*/')
    with pytest.raises(build.BuildError, match='nesting'):
        styles.parse('a{' * 65 + '}' * 65)
    with pytest.raises(build.BuildError, match='tokens|nodes'):
        styles.parse('a{}' * 25_001)
    with pytest.raises(build.BuildError, match='UTF-8'):
        styles.parse('p {content: "\ud800"}')


def test_brackets_and_comments_inside_strings_do_not_count_as_nesting():
    assert styles.parse('p::after {content: "' + '{[' * 100 + '/*"}').urls == []


def test_validation_resolves_image_set_and_percent_encoded_assets(tmp_path: Path):
    (tmp_path / "it's.svg").write_text('<svg/>')
    styles.validate('a {background: image-set("it%27s.svg?v=1#icon" 1x)}', tmp_path)
    with pytest.raises(build.BuildError, match='not found'):
        styles.validate('a {background: image-set("missing.svg" 1x)}', tmp_path)


def test_regular_builds_allow_imports_without_loading_them(tmp_path: Path):
    styles.validate('@import "https://example.invalid/theme.css"; p {color: red}', tmp_path)


def test_asset_paths_cannot_escape_or_follow_symlinks(tmp_path: Path):
    with pytest.raises(build.BuildError, match='escapes'):
        styles.asset_path(tmp_path, '%2Ftmp%2Foutside.svg')
    with pytest.raises(build.BuildError, match='escapes'):
        styles.asset_path(tmp_path, '../outside.svg')
    outside = tmp_path / 'source.svg'
    outside.write_text('<svg/>')
    (tmp_path / 'linked.svg').symlink_to(outside)
    with pytest.raises(build.BuildError, match='symlink'):
        styles.asset_path(tmp_path, 'linked.svg')


def test_builder_accepts_a_server_validator_without_parsing_css_itself(tmp_path: Path):
    (tmp_path / 'main.md').write_text('# Test\n')
    css = '.page::after {content: "url(sample.svg)"}'
    (tmp_path / 'styles.css').write_text(css)
    checked: list[str] = []

    def validate(source: str, base: Path) -> None:
        assert base == tmp_path
        checked.append(source)

    assert build.build_html(tmp_path, css_validator=validate).is_file()
    assert checked == [css]


@pytest.mark.parametrize('url', ['asset%00.svg', 'assets%5Coutside.svg'])
def test_invalid_decoded_paths_raise_a_build_error(tmp_path: Path, url: str):
    with pytest.raises(build.BuildError, match='characters'):
        styles.asset_path(tmp_path, url)


def test_standalone_builder_runs_without_site_packages(tmp_path: Path):
    (tmp_path / 'main.md').write_text('# Standalone\n')
    result = subprocess.run(
        [
            sys.executable,
            '-S',
            '-c',
            'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import build; build.build_html(Path(sys.argv[2]))',
            str(Path(__file__).resolve().parent.parent / 'backend'),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'dist/index.html').is_file()
