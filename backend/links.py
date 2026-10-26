"""Read bounded HTML/CSS reference facts, with SSRF protection on every network request."""

from __future__ import annotations

from collections import Counter, defaultdict
from html.parser import HTMLParser
from typing import cast
from urllib.parse import urljoin

import httpx2
import styles
import tinycss2
from pydantic_ai._ssrf import safe_download
from tinycss2 import ast
from tinycss2.color3 import parse_color

import build

PAGE_MAX_BYTES = 2 * 1024 * 1024
SHEET_MAX_BYTES = 1024 * 1024
MAX_SHEETS = 10
IMAGE_MAX_BYTES = 5 * 1024 * 1024
download = safe_download


class LinkError(Exception):
    """A public reference could not be read."""


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.sheets: list[str] = []
        self.css: list[str] = []
        self.logos: list[str] = []
        self.icons: list[str] = []
        self.social: list[str] = []
        self.in_title = False
        self.in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.in_title = self.in_title or tag == 'title'
        self.in_style = self.in_style or tag == 'style'
        if tag == 'link':
            rel = (values.get('rel') or '').lower().split()
            href = values.get('href')
            if href and 'stylesheet' in rel:
                self.sheets.append(href)
            if href and any('icon' in item for item in rel):
                self.icons.append(href)
        if (
            tag == 'img'
            and 'logo' in ' '.join(values.get(k) or '' for k in ('src', 'alt', 'class', 'id')).lower()
            and (src := values.get('src'))
        ):
            self.logos.append(src)
        if tag == 'meta' and values.get('property') == 'og:image' and (content := values.get('content')):
            self.social.append(content)
        if inline := values.get('style'):
            self.css.append(f'{tag} {{ {inline} }}')

    def handle_endtag(self, tag: str) -> None:
        if tag == 'title':
            self.in_title = False
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if self.in_style:
            self.css.append(data)


def color_hex(value: str) -> str | None:
    color = cast(tuple[float, float, float, float] | str | None, parse_color(value))
    if not isinstance(color, tuple):
        return None
    channels = [max(0, min(255, round(c * 255))) for c in color]
    return '#' + ''.join(f'{c:02x}' for c in (channels[:3] if channels[3] == 255 else channels))


def page_facts(base_url: str, html: str, sheets: list[tuple[str, str]]) -> str:
    page = Page()
    page.feed(html)
    tokens: dict[str, str] = {}
    fonts: Counter[str] = Counter()
    faces: set[str] = set()
    colors: Counter[str] = Counter()
    selectors: dict[str, list[str]] = defaultdict(list)

    def walk(rules: list[ast.Node]) -> None:
        for rule in rules:
            if not isinstance(rule, (ast.QualifiedRule, ast.AtRule)) or rule.content is None:
                continue
            if isinstance(rule, ast.AtRule) and rule.lower_at_keyword != 'font-face':
                walk(list(tinycss2.parse_rule_list(rule.content)))
                continue
            selector = tinycss2.serialize(rule.prelude).strip() if isinstance(rule, ast.QualifiedRule) else '@font-face'
            for decl in tinycss2.parse_declaration_list(rule.content):
                if not isinstance(decl, ast.Declaration):
                    continue
                value = tinycss2.serialize(decl.value).strip()
                if decl.name.startswith('--') and selector in (':root', 'html', 'body') and len(tokens) < 40:
                    tokens[decl.name] = value
                if decl.lower_name == 'font-family':
                    if selector == '@font-face':
                        faces.add(value.strip('"\''))
                    else:
                        fonts[value] += 1
                for token in decl.value:
                    color = color_hex(tinycss2.serialize([token]))
                    if color:
                        colors[color] += 1
                        if selector not in selectors[color] and len(selectors[color]) < 3:
                            selectors[color].append(selector[:200])

    for _, css in [(base_url, '\n'.join(page.css)), *sheets]:
        try:
            walk(styles.parse(css, allow_imports=True).rules)
        except (ValueError, build.BuildError):
            continue
    candidates = list(
        dict.fromkeys(
            urljoin(base_url, url)
            for url in [*page.logos, *sorted(page.icons, key=lambda p: not p.lower().endswith('.svg')), *page.social]
        )
    )[:20]
    facts = [
        f'title: {page.title.strip()[:500]}',
        *(f'{k}: {v[:500]}' for k, v in tokens.items()),
        *(f'font-family {f[:500]} ({n})' for f, n in fonts.most_common(8)),
        *(f'@font-face: {f[:500]}' for f in sorted(faces)[:8]),
        *(f'{c} ({n}): {", ".join(selectors[c])}' for c, n in colors.most_common(12)),
        'logo candidates:',
        *candidates,
    ]
    return '\n'.join(facts)


async def read_link(url: str) -> str:
    try:
        response = await download(url, max_bytes=PAGE_MAX_BYTES)
        if response.status_code != 200:
            return f'The page answered {response.status_code}: it could not be inspected as the site itself.'
        if 'html' not in response.headers.get('content-type', 'text/html').lower():
            raise LinkError(f'could not read {url}: expected an HTML page')
        page = Page()
        page.feed(response.text)
        sheets: list[tuple[str, str]] = []
        failures: list[str] = []
        for href in list(dict.fromkeys(page.sheets))[:MAX_SHEETS]:
            sheet_url = urljoin(str(response.url), href)
            try:
                sheet = await download(sheet_url, max_bytes=SHEET_MAX_BYTES, timeout=10)
                sheets.append((str(sheet.url), sheet.text))
            except (httpx2.HTTPError, ValueError) as exc:
                failures.append(f'Could not read stylesheet {sheet_url}: {exc}')
        return (
            str(response.url) + '\n' + page_facts(str(response.url), response.text, sheets) + '\n' + '\n'.join(failures)
        )
    except httpx2.HTTPStatusError as exc:
        return f'The page answered {exc.response.status_code}: it could not be inspected as the site itself.'
    except (httpx2.HTTPError, ValueError) as exc:
        raise LinkError(f'could not read {url}: {exc}') from exc


async def download_image(url: str) -> tuple[str, bytes]:
    try:
        response = await download(url, max_bytes=IMAGE_MAX_BYTES)
        media = response.headers.get('content-type', '').partition(';')[0].strip().lower()
        if media not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml'):
            raise ValueError('expected a PNG, JPEG, GIF, WebP or SVG image')
        return media, response.content
    except (httpx2.HTTPError, ValueError) as exc:
        raise LinkError(f'could not read {url}: {exc}') from exc
