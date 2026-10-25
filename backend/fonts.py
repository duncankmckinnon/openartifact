"""Install bounded Google Fonts downloads as local WOFF2 assets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx2
import styles
import tinycss2
from pydantic_ai._ssrf import safe_download
from tinycss2 import ast

CSS_API = 'https://fonts.googleapis.com/css2'
FONT_HOST = 'fonts.gstatic.com'
SUBSETS = ('latin', 'latin-ext')
USER_AGENT = 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
download = safe_download


class FontError(ValueError):
    """A font cannot be downloaded from the supported provider."""


@dataclass(frozen=True)
class FontFile:
    path: str
    weight: int
    style: str
    unicode_range: str | None
    data: bytes


def slug(family: str) -> str:
    result = re.sub(r'[^a-z0-9]+', '-', family.lower()).strip('-')
    if not result or len(family) > 100 or not re.fullmatch(r'[\w -]+', family):
        raise FontError('provide a Google Fonts family name')
    return result


async def fetch_family(family: str, weights: list[int], italic: bool) -> list[FontFile]:
    name = slug(family)
    weights = sorted(set(weights))
    if not weights or len(weights) > 6 or any(w not in range(100, 901, 100) for w in weights):
        raise FontError('choose 1 to 6 weights from 100 to 900 in steps of 100')
    variants = ';'.join(f'{i},{w}' for i in ([0, 1] if italic else [0]) for w in weights)
    url = CSS_API + '?' + urlencode({'family': f'{family}:ital,wght@{variants}', 'display': 'swap'})
    try:
        response = await download(
            url,
            allowed_domains=['fonts.googleapis.com'],
            max_redirects=0,
            max_bytes=1024 * 1024,
            headers={'User-Agent': USER_AGENT},
        )
        rules = styles.parse(response.text).rules
        subset = ''
        files: list[FontFile] = []
        cache: dict[str, bytes] = {}
        for rule in rules:
            if isinstance(rule, ast.Comment):
                subset = rule.value.strip()
            if (
                not isinstance(rule, ast.AtRule)
                or rule.lower_at_keyword != 'font-face'
                or rule.content is None
                or subset not in SUBSETS
            ):
                continue
            declarations = {
                d.lower_name: tinycss2.serialize(d.value).strip()
                for d in tinycss2.parse_declaration_list(rule.content)
                if isinstance(d, ast.Declaration)
            }
            weight = int(declarations.get('font-weight', '400'))
            if weight not in weights:
                continue
            style = declarations.get('font-style', 'normal')
            urls = styles.parse(tinycss2.serialize([rule])).urls
            if not urls:
                raise FontError('Google Fonts returned no font URL')
            font_url = urls[0]
            parsed = urlsplit(font_url)
            if (
                parsed.scheme != 'https'
                or parsed.hostname != FONT_HOST
                or parsed.port not in (None, 443)
                or parsed.username
                or parsed.password
            ):
                raise FontError('unexpected font host')
            if font_url not in cache:
                font = await download(font_url, allowed_domains=[FONT_HOST], max_redirects=0, max_bytes=5 * 1024 * 1024)
                cache[font_url] = font.content
            data = cache[font_url]
            if not data.startswith(b'wOF2'):
                raise FontError('Google Fonts returned an invalid WOFF2 font')
            if sum(len(f.data) for f in files) + len(data) > styles.MAX_ASSET_BYTES:
                raise FontError('font family exceeds the saved-style asset limit')
            path = f'fonts/{name}-{weight}{"-italic" if style == "italic" else ""}-{subset}.woff2'
            files.append(FontFile(path, weight, style, declarations.get('unicode-range'), data))
        if not files:
            raise FontError(f'{family} has no supported Latin WOFF2 fonts')
        return files
    except httpx2.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            raise FontError(f'{family} is not a Google Fonts family, or lacks those weights') from exc
        raise FontError(f'could not download {family}: HTTP {exc.response.status_code}') from exc
    except (httpx2.HTTPError, ValueError) as exc:
        raise FontError(str(exc)) from exc


def font_face_css(family: str, files: list[FontFile]) -> str:
    return '\n'.join(
        '@font-face {\n'
        f'  font-family: {styles.quoted_string(family)};\n'
        f'  font-style: {f.style};\n  font-weight: {f.weight};\n  font-display: swap;\n'
        f'  src: url({styles.quoted_string(f.path)}) format("woff2");\n'
        + (f'  unicode-range: {f.unicode_range};\n' if f.unicode_range else '')
        + '}'
        for f in files
    )
