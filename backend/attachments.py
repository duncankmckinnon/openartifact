"""Bounded, transient chat references. Office files become facts and a small selection of embedded images."""

from __future__ import annotations

import base64
import binascii
import io
import mimetypes
import zipfile
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from pydantic_ai.messages import (
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.ui.vercel_ai.request_types import FileUIPart, TextUIPart, UIMessage, UIMessagePart

MAX_FILES = 5
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 30 * 1024 * 1024
MAX_MEDIA = 8
MAX_MEDIA_BYTES = 1024 * 1024
ZIP_MAX_MEMBERS = 2000
ZIP_MAX_BYTES = 200 * 1024 * 1024
XML_MAX_BYTES = 5 * 1024 * 1024
SVG_TEXT_LIMIT = 50_000
MODEL_IMAGE_TYPES = frozenset({'image/png', 'image/jpeg', 'image/gif', 'image/webp'})
OFFICE_KINDS = {'.pptx': 'PowerPoint', '.docx': 'Word'}
NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
}
W = '{' + NS['w'] + '}'


class AttachmentError(ValueError):
    """A reference cannot be accepted or safely expanded."""


@dataclass(frozen=True)
class Attachment:
    name: str
    media_type: str
    data: bytes


def xml_part(archive: zipfile.ZipFile, path: str) -> ET.Element | None:
    try:
        info = archive.getinfo(path)
    except KeyError:
        return None
    if info.file_size > XML_MAX_BYTES:
        raise AttachmentError('XML is too large to read safely')
    data = archive.read(info)
    # Office XML needs no DTDs or entity declarations.
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise AttachmentError('XML declarations cannot be read safely')
    return ET.fromstring(data)


def office_facts(name: str, data: bytes) -> tuple[str, list[Attachment]]:
    kind = OFFICE_KINDS.get(PurePosixPath(name).suffix.lower())
    prefix = 'ppt' if kind == 'PowerPoint' else 'word'
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > ZIP_MAX_MEMBERS or sum(i.file_size for i in infos) > ZIP_MAX_BYTES:
                raise AttachmentError(f'{name} is too large to read safely')
            main = xml_part(archive, f'{prefix}/presentation.xml' if prefix == 'ppt' else 'word/document.xml')
            if kind is None or main is None:
                raise ValueError('missing main part')
            facts: list[str] = []
            theme = xml_part(archive, f'{prefix}/theme/theme1.xml')
            if theme is not None:
                colors = theme.find('.//a:clrScheme', NS)
                if colors is not None:
                    for color in colors:
                        for value in color:
                            hex_value = value.get('lastClr') or value.get('val', '')
                            if len(hex_value) == 6 and all(c in '0123456789abcdefABCDEF' for c in hex_value):
                                facts.append(f'theme colour {color.tag.split("}")[-1]}: #{hex_value.upper()}')
                for role, tag in (('heading', 'majorFont'), ('body', 'minorFont')):
                    font = theme.find(f'.//a:{tag}/a:latin', NS)
                    if font is not None and font.get('typeface'):
                        facts.append(f'{role} font: {font.get("typeface")}')
            if prefix == 'ppt':
                size = main.find('p:sldSz', NS)
                if size is not None:
                    facts.append(
                        f'slide size: {int(size.get("cx", "0")) / 914400:g} x {int(size.get("cy", "0")) / 914400:g} in'
                    )
                facts.append(f'slides: {len(main.findall("p:sldIdLst/p:sldId", NS))}')
            else:
                styles = xml_part(archive, 'word/styles.xml')
                if styles is not None:
                    for style in styles.findall('w:style', NS):
                        label = style.find('w:name', NS)
                        label_value = label.get(W + 'val', '') if label is not None else ''
                        normalized = label_value.lower().replace(' ', '')
                        labels = {
                            'title': 'Title',
                            'heading1': 'Heading 1',
                            'heading2': 'Heading 2',
                            'heading3': 'Heading 3',
                            'normal': 'Normal',
                        }
                        if normalized not in labels:
                            continue
                        values: list[str] = []
                        for tag, attr in (('sz', 'val'), ('rFonts', 'ascii'), ('b', 'val'), ('color', 'val')):
                            node = style.find(f'w:rPr/w:{tag}', NS)
                            if node is None:
                                continue
                            value = node.get(W + attr, '')
                            if tag == 'sz' and value:
                                values.append(f'{float(value) / 2:g}pt')
                            elif tag == 'b' and value not in ('0', 'false', 'off'):
                                values.append('bold')
                            elif tag == 'color' and len(value) == 6:
                                values.append(f'colour #{value.upper()}')
                            elif tag == 'rFonts' and value:
                                values.append(value)
                        facts.append(f'{labels[normalized]}: {", ".join(values)}')
            media = [
                i
                for i in infos
                if i.filename.startswith(f'{prefix}/media/')
                and PurePosixPath(i.filename).suffix.lower() in ('.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp')
                and i.file_size <= MAX_MEDIA_BYTES
            ]
            media.sort(
                key=lambda i: (
                    PurePosixPath(i.filename).suffix.lower() not in ('.svg', '.png'),
                    i.file_size,
                    i.filename,
                )
            )
            images = [
                Attachment(
                    f'{name}/{PurePosixPath(i.filename).name}',
                    mimetypes.guess_type(i.filename)[0] or 'image/png',
                    archive.read(i),
                )
                for i in media[:MAX_MEDIA]
            ]
            return '\n'.join(facts), images
    except AttachmentError:
        raise
    except (ValueError, KeyError, OSError, RuntimeError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise AttachmentError(f'{name} is not a PowerPoint or Word file') from exc


def image_parts(image: Attachment) -> list[UIMessagePart]:
    if image.media_type == 'image/svg+xml':
        return [TextUIPart(text=f'```svg\n{image.data.decode("utf-8", "replace")[:SVG_TEXT_LIMIT]}\n```')]
    return [
        FileUIPart(
            media_type=image.media_type,
            filename=image.name,
            url=f'data:{image.media_type};base64,{base64.b64encode(image.data).decode()}',
        )
    ]


def prepare(message: UIMessage) -> tuple[UIMessage, dict[str, Attachment]]:
    file_parts = [p for p in message.parts if isinstance(p, FileUIPart)]
    if len(file_parts) > MAX_FILES:
        raise AttachmentError('attach up to 5 files')
    parts: list[UIMessagePart] = []
    files: dict[str, Attachment] = {}
    total = 0
    for part in message.parts:
        if not isinstance(part, FileUIPart):
            parts.append(part)
            continue
        name = part.filename or f'attachment-{len(files) + 1}'
        if name in files:
            raise AttachmentError(f'{name}: use distinct filenames')
        header, separator, encoded = part.url.partition(',')
        if not separator or not header.startswith('data:') or not header.endswith(';base64'):
            raise AttachmentError(f'{name}: attach a file as a base64 data URL')
        if len(encoded) > ((MAX_TOTAL_BYTES - total + 2) // 3) * 4:
            raise AttachmentError('attachments are limited to 20 MB in all')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AttachmentError(f'{name}: invalid base64 attachment') from exc
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise AttachmentError('attachments are limited to 20 MB in all')
        suffix = PurePosixPath(name).suffix.lower()
        media_type = header[5:-7].lower()
        office = OFFICE_KINDS.get(suffix)
        image = media_type in MODEL_IMAGE_TYPES or media_type == 'image/svg+xml'
        if not office and not image and media_type != 'application/pdf':
            raise AttachmentError(f'{name}: attach a PDF, PowerPoint or Word file, or an image')
        if image and len(data) > MAX_IMAGE_BYTES:
            raise AttachmentError(f'{name} is over 5 MB')
        stored_media = (
            'application/vnd.openxmlformats-officedocument.presentationml.presentation'
            if office == 'PowerPoint'
            else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            if office == 'Word'
            else media_type
        )
        files[name] = Attachment(name, stored_media, data)
        label = office or ('image' if image else 'PDF')
        parts.append(TextUIPart(text=f'Attached {name} ({label}).'))
        if office:
            facts, images = office_facts(name, data)
            parts.append(TextUIPart(text=facts))
            for embedded in images:
                files[embedded.name] = embedded
                parts.append(TextUIPart(text=f'Embedded image {embedded.name}.'))
                parts.extend(image_parts(embedded))
        elif media_type == 'image/svg+xml':
            parts.extend(image_parts(files[name]))
        else:
            parts.append(FileUIPart(media_type=media_type, filename=name, url=part.url))
    return message.model_copy(update={'parts': parts}), files


def strip(
    messages: list[ModelMessage], transient: frozenset[str] = frozenset(), *, start_index: int = 0
) -> list[ModelMessage]:
    """Copy history without binary inputs or generated reference text; never mutate a run's messages."""
    result: list[ModelMessage] = []
    for index, message in enumerate(messages):
        if not isinstance(message, ModelRequest):
            result.append(message)
            continue
        parts: list[ModelRequestPart] = []
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.tool_name == 'look_at_link':
                parts.append(replace(part, content='Reference inspected during that turn; see the derived brief.'))
                continue
            if isinstance(part, UserPromptPart):
                content = [part.content] if isinstance(part.content, str) else part.content
                kept = [
                    item
                    for item in content
                    if not isinstance(item, (BinaryContent, ImageUrl, DocumentUrl))
                    and not (index >= start_index and isinstance(item, str) and item in transient)
                ]
                parts.append(replace(part, content=kept))
            else:
                parts.append(part)
        result.append(replace(message, parts=parts))
    return result
