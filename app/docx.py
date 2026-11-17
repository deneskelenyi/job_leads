"""Minimal .docx generation — no dependencies.

A WordprocessingML package: one A4 section, Arial 11pt, one external
hyperlink (the job posting). Enough for letter downloads; Word, Pages,
LibreOffice and textutil all open the result.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

FONT = "Arial"
LINK_COLOR = "0563C1"

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdLink" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{target}" TargetMode="External"/>
</Relationships>"""


def _rpr(sz: int = 22, color: str | None = None, underline: bool = False) -> str:
    color_xml = f'<w:color w:val="{color}"/>' if color else ""
    u_xml = '<w:u w:val="single"/>' if underline else ""
    return (f'<w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>'
            f"{color_xml}{u_xml}<w:sz w:val=\"{sz}\"/><w:szCs w:val=\"{sz}\"/></w:rPr>")


def _runs(text: str, sz: int = 22) -> str:
    """Escape text; newlines become <w:br/> line breaks."""
    parts = escape(text).split("\n")
    runs = []
    for i, part in enumerate(parts):
        if i:
            runs.append("<w:br/>")
        if part:
            runs.append(f'<w:r>{_rpr(sz)}<w:t xml:space="preserve">{part}</w:t></w:r>')
    return "".join(runs)


def _para(runs: str) -> str:
    return f"<w:p><w:pPr><w:spacing w:after=\"200\"/></w:pPr>{runs}</w:p>"


def build_letter_docx(letter: str, job_title: str = "", company: str = "",
                      url: str = "") -> bytes:
    """A cover-letter .docx: Re: line (posting hyperlinked), then the letter."""
    paras: list[str] = []

    if job_title:
        re_text = f"Re: {job_title}" + (f" — {company}" if company else "") + " "
        runs = (f'<w:r>{_rpr()}<w:t xml:space="preserve">{escape(re_text)}</w:t></w:r>')
        if url:
            runs += (f'<w:hyperlink r:id="rIdLink" w:history="1">'
                     f'<w:r>{_rpr(color=LINK_COLOR, underline=True)}'
                     f'<w:t xml:space="preserve">(view posting)</w:t></w:r>'
                     f'</w:hyperlink>')
        paras.append(_para(runs))
        paras.append("<w:p/>")

    body = (letter or "").replace("\r\n", "\n").strip()
    for block in body.split("\n\n"):
        if block.strip():
            paras.append(_para(_runs(block.strip())))

    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
            'w:left="1440" w:header="708" w:footer="708"/></w:sectPr>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document'
                ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
                ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<w:body>{"".join(paras)}{sect}</w:body></w:document>')

    target = escape(url, {'"': "&quot;"}) if url else "https://example.com"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels",
                   _DOC_RELS.format(target=target))
        z.writestr("word/document.xml", document)
    return out.getvalue()


def letter_filename(job_title: str = "", company: str = "") -> str:
    base = (company or job_title or "job").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:40] or "job"
    return f"cover_letter_{slug}.docx"
