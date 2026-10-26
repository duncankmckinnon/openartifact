"""Reference extraction and retention, with bounded synthetic files and no provider calls."""

from __future__ import annotations

import base64
import io
import zipfile

import attachments as a
import pytest
from pydantic_ai.messages import BinaryContent, ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.ui.vercel_ai.request_types import FileUIPart, TextUIPart, UIMessage


def file_part(name: str, media_type: str, data: bytes) -> FileUIPart:
    return FileUIPart(
        filename=name, media_type=media_type, url=f'data:{media_type};base64,{base64.b64encode(data).decode()}'
    )


def office(parts: dict[str, str | bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return stream.getvalue()


def powerpoint() -> bytes:
    return office(
        {
            'ppt/presentation.xml': f'<p:presentation xmlns:p="{a.NS["p"]}"><p:sldIdLst><p:sldId/></p:sldIdLst><p:sldSz cx="9144000" cy="5143500"/></p:presentation>',
            'ppt/theme/theme1.xml': f'<a:theme xmlns:a="{a.NS["a"]}"><a:clrScheme><a:accent1><a:srgbClr val="FF6B4A"/></a:accent1></a:clrScheme><a:majorFont><a:latin typeface="Söhne"/></a:majorFont><a:minorFont><a:latin typeface="Inter"/></a:minorFont></a:theme>',
            'ppt/media/photo.jpg': b'x' * 2048,
            'ppt/media/logo.png': b'png',
            'ppt/media/large.png': b'x' * (a.MAX_MEDIA_BYTES + 1),
        }
    )


def test_office_detected_by_extension_and_media_prefer_small_images():
    message, files = a.prepare(
        UIMessage(id='u', role='user', parts=[file_part('brand.pptx', 'application/octet-stream', powerpoint())])
    )
    assert isinstance(message.parts[0], TextUIPart) and message.parts[0].text == 'Attached brand.pptx (PowerPoint).'
    facts = message.parts[1]
    assert isinstance(facts, TextUIPart)
    for expected in (
        'theme colour accent1: #FF6B4A',
        'heading font: Söhne',
        'body font: Inter',
        'slides: 1',
        'slide size: 10 x 5.625 in',
    ):
        assert expected in facts.text
    assert list(files) == ['brand.pptx', 'brand.pptx/logo.png', 'brand.pptx/photo.jpg']
    assert isinstance(message.parts[3], FileUIPart) and message.parts[3].media_type == 'image/png'


def test_docx_heading_styles():
    data = office(
        {
            'word/document.xml': f'<w:document xmlns:w="{a.NS["w"]}"/>',
            'word/styles.xml': f'<w:styles xmlns:w="{a.NS["w"]}"><w:style><w:name w:val="heading 1"/><w:rPr><w:sz w:val="40"/><w:rFonts w:ascii="Fraunces"/><w:b/></w:rPr></w:style></w:styles>',
        }
    )
    facts, images = a.office_facts('brand.docx', data)
    assert 'Heading 1: 20pt, Fraunces, bold' in facts
    assert images == []


def test_svg_as_text_and_binary_inputs_are_stripped():
    original = UIMessage(
        id='u',
        role='user',
        parts=[TextUIPart(text='Use this'), file_part('logo.svg', 'image/svg+xml', b'<svg>secret reference</svg>')],
    )
    prepared, _ = a.prepare(original)
    svg = prepared.parts[-1]
    assert isinstance(svg, TextUIPart) and svg.text.startswith('```svg')
    history: list[ModelMessage] = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    [
                        'Use this',
                        'Attached logo.svg (image).',
                        svg.text,
                        BinaryContent(b'%PDF', media_type='application/pdf'),
                    ]
                )
            ]
        )
    ]
    stripped = a.strip(history, frozenset({svg.text}))
    request = stripped[0]
    assert isinstance(request, ModelRequest)
    part = request.parts[0]
    assert isinstance(part, UserPromptPart) and part.content == ['Use this', 'Attached logo.svg (image).']
    original_request = history[0]
    assert isinstance(original_request, ModelRequest)
    original_part = original_request.parts[0]
    assert isinstance(original_part, UserPromptPart) and len(original_part.content) == 4


@pytest.mark.parametrize(
    ('name', 'mime', 'data'), [('a.pdf', 'application/pdf', b'%PDF'), ('a.png', 'image/png', b'png')]
)
def test_file_only_messages_pass_through(name: str, mime: str, data: bytes):
    original = file_part(name, mime, data)
    prepared, files = a.prepare(UIMessage(id='u', role='user', parts=[original]))
    assert prepared.parts[-1] == original
    assert files[name].data == data


@pytest.mark.parametrize(
    ('parts', 'error'),
    [
        ([file_part(f'{i}.png', 'image/png', b'x') for i in range(6)], '5 files'),
        ([file_part('a.png', 'image/png', b'x' * (a.MAX_IMAGE_BYTES + 1))], '5 MB'),
        ([file_part('a.txt', 'text/plain', b'x')], 'attach a PDF'),
        ([file_part('a.pptx', 'application/octet-stream', b'bad')], 'not a PowerPoint'),
        ([FileUIPart(filename='a.png', media_type='image/png', url='https://example.com/a.png')], 'data URL'),
        ([FileUIPart(filename='a.png', media_type='image/png', url='data:image/png;base64,%%%')], 'base64'),
    ],
)
def test_limits_and_invalid_inputs(parts: list[FileUIPart], error: str):
    with pytest.raises(a.AttachmentError, match=error):
        a.prepare(UIMessage(id='u', role='user', parts=[*parts]))


def test_total_and_zip_limits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(a, 'MAX_TOTAL_BYTES', 10)
    with pytest.raises(a.AttachmentError, match='20 MB'):
        a.prepare(UIMessage(id='u', role='user', parts=[file_part('a.pdf', 'application/pdf', b'x' * 11)]))
    monkeypatch.setattr(a, 'ZIP_MAX_BYTES', 10)
    with pytest.raises(a.AttachmentError, match='too large'):
        a.office_facts('a.pptx', powerpoint())


def test_transient_text_removal_preserves_previous_turns():
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart('reference facts')]),
        ModelRequest(parts=[UserPromptPart(['Attached brand.pptx (PowerPoint).', 'reference facts'])]),
    ]
    result = a.strip(messages, frozenset({'reference facts'}), start_index=1)
    first, second = result
    assert isinstance(first, ModelRequest) and isinstance(second, ModelRequest)
    old, current = first.parts[0], second.parts[0]
    assert isinstance(old, UserPromptPart) and old.content == ['reference facts']
    assert isinstance(current, UserPromptPart) and current.content == ['Attached brand.pptx (PowerPoint).']
