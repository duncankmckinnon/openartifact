"""Bounded CSS parsing and asset rewriting for the server, using tinycss2's syntax tree.

The standalone builder receives `validate` as a callback and never imports this module or tinycss2.
Parsing does not fetch stylesheets or assets; saved styles reject imports, while ordinary builds leave
browser-managed imports unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import tinycss2
from tinycss2 import ast
from tinycss2.serializer import serialize_string_value

import build

MAX_CSS_BYTES = 1_000_000
MAX_NODES = 50_000
MAX_NESTING = 64
MAX_REFERENCES = 1024
MAX_ASSETS = 256
MAX_ASSET_BYTES = 20_000_000

Reference = ast.URLToken | ast.StringToken


def quoted_string(value: str) -> str:
    """Escape a CSS string for a live HTML style block without changing its decoded value."""
    escaped = serialize_string_value(value).replace('<', r'\3c ')
    return f'"{escaped}"'


@dataclass
class Stylesheet:
    """Parsed CSS with only the string/URL nodes that actually name image or font resources."""

    rules: list[ast.Node]
    references: list[Reference]

    @property
    def urls(self) -> list[str]:
        """Decoded resource URLs, excluding ordinary strings, comments and imported stylesheets."""
        return [node.value for node in self.references]

    def rewrite(self, replace: Callable[[str], str]) -> str:
        """Rewrite resource values and serialize them with CSS string escaping."""
        for node in self.references:
            value = replace(node.value)
            if value == node.value:
                continue
            node.value = value
            quoted = quoted_string(value)
            node.representation = f'url({quoted})' if isinstance(node, ast.URLToken) else quoted
        return tinycss2.serialize(self.rules)


def children(node: ast.Node) -> list[ast.Node]:
    """The syntax-tree children, without parsing declaration values as a second language."""
    if isinstance(node, ast.FunctionBlock):
        return node.arguments
    if isinstance(node, (ast.ParenthesesBlock, ast.SquareBracketsBlock, ast.CurlyBracketsBlock)):
        return node.content
    if isinstance(node, (ast.QualifiedRule, ast.AtRule)):
        return [*node.prelude, *(node.content or [])]
    return []


def image_set_strings(node: ast.FunctionBlock) -> list[ast.StringToken]:
    """Only the leading string in each image-set candidate is a URL; type() strings are MIME types."""
    found: list[ast.StringToken] = []
    first = True
    for token in node.arguments:
        if isinstance(token, (ast.WhitespaceToken, ast.Comment)):
            continue
        if isinstance(token, ast.LiteralToken) and token.value == ',':
            first = True
        else:
            if first and isinstance(token, ast.StringToken):
                found.append(token)
            first = False
    return found


def parse(css: str, *, allow_imports: bool = False) -> Stylesheet:
    """Parse bounded CSS and discover resource nodes, including escaped names and image-set strings.

    tinycss2 tokenizes blocks iteratively. The byte limit bounds initial parsing, and an iterative walk
    limits node count and nesting before serialization or filesystem access. An unfinished comment at EOF
    is valid CSS syntax and is consumed once by the parser.
    """
    if len(css) > MAX_CSS_BYTES:
        raise build.BuildError(f'CSS is too large; maximum size is {MAX_CSS_BYTES:,} UTF-8 bytes')
    try:
        size = len(css.encode('utf-8'))
    except UnicodeError as exc:
        raise build.BuildError('CSS must contain valid UTF-8 text') from exc
    if size > MAX_CSS_BYTES:
        raise build.BuildError(f'CSS is too large; maximum size is {MAX_CSS_BYTES:,} UTF-8 bytes')
    try:
        rules: list[ast.Node] = list(tinycss2.parse_stylesheet(css))
    except (ValueError, RecursionError) as exc:
        raise build.BuildError(f'CSS could not be parsed: {exc}') from exc
    references: list[Reference] = []
    work = [(node, 1, False) for node in reversed(rules)]
    count = 0
    while work:
        node, depth, imported = work.pop()
        count += 1
        if count > MAX_NODES:
            raise build.BuildError(f'CSS has too many syntax nodes; maximum is {MAX_NODES:,}')
        if depth > MAX_NESTING:
            raise build.BuildError(f'CSS nesting exceeds {MAX_NESTING} levels')
        if isinstance(node, ast.ParseError):
            raise build.BuildError(f'CSS:{node.source_line}:{node.source_column}: {node.message}')
        # Parsing normalizes escapes even in ordinary strings. Keep those values safe when the whole
        # sheet is serialized into the builder's live <style> block, including unchanged URL nodes.
        if isinstance(node, ast.StringToken):
            node.representation = quoted_string(node.value)
        elif isinstance(node, ast.URLToken):
            node.representation = f'url({quoted_string(node.value)})'
        is_import = (isinstance(node, ast.AtRule) and node.lower_at_keyword == 'import') or (
            isinstance(node, ast.AtKeywordToken) and node.lower_value == 'import'
        )
        if is_import and not allow_imports:
            raise build.BuildError('CSS @import is not supported in saved styles; combine the stylesheets first')
        imported = imported or is_import
        if not imported:
            if isinstance(node, ast.URLToken):
                references.append(node)
            elif isinstance(node, ast.FunctionBlock):
                if node.lower_name == 'url':
                    arguments = [n for n in node.arguments if not isinstance(n, (ast.Comment, ast.WhitespaceToken))]
                    if len(arguments) != 1 or not isinstance(arguments[0], ast.StringToken):
                        raise build.BuildError(f'CSS:{node.source_line}: invalid url() value')
                    references.append(arguments[0])
                elif node.lower_name in ('image-set', '-webkit-image-set'):
                    references.extend(image_set_strings(node))
        if len(references) > MAX_REFERENCES:
            raise build.BuildError(f'CSS contains more than {MAX_REFERENCES:,} resource references')
        work.extend((child, depth + 1, imported) for child in reversed(children(node)))
    references.sort(key=lambda node: (node.source_line, node.source_column))
    return Stylesheet(rules, references)


def asset_path(base: Path, url: str) -> Path | None:
    """Resolve a local image/font safely; external URLs and local SVG fragments stay unchanged."""
    if not url or url.startswith('#') or build.is_external(url):
        return None
    if '\\' in url or any(ord(char) < 32 for char in url):
        raise build.BuildError(f'unsupported characters in CSS asset URL: {url!r}')
    key = unquote(urlsplit(url).path)
    if '\\' in key or any(ord(char) < 32 for char in key):
        raise build.BuildError(f'unsupported characters in CSS asset URL: {url!r}')
    root = base.resolve()
    path = root / key
    if Path(key).is_absolute() or '..' in Path(key).parts or not path.resolve().is_relative_to(root):
        raise build.BuildError(f'CSS asset path escapes the artifact: {url!r}')
    if path.suffix.lower() not in (*build.IMAGE_EXTS, '.woff', '.woff2'):
        raise build.BuildError(f'unsupported CSS asset: {url!r}; use an image or WOFF font')
    current = path
    while current != root:
        if current.is_symlink():
            raise build.BuildError(f'CSS asset symlinks cannot be copied: {url!r}')
        current = current.parent
    if not key or not path.is_file():
        raise build.BuildError(f'CSS asset not found: {url!r}')
    return path


def validate(css: str, base: Path) -> None:
    """Validate CSS and its local assets on every server build, without resolving browser imports."""
    sheet = parse(css, allow_imports=True)
    assets = {path for url in sheet.urls if (path := asset_path(base, url)) is not None}
    if len(assets) > MAX_ASSETS:
        raise build.BuildError(f'CSS references too many local assets; maximum is {MAX_ASSETS}')
