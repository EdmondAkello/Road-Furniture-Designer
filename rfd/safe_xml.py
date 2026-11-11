"""Refuse LandXML files that declare a DOCTYPE or entities, before they are parsed.

A LandXML file can come from anywhere (a shared drive, an email, a download), so it is untrusted
input. The stdlib parser still expands general entities declared in a document's own DOCTYPE: a
file with a few nested entities ("billion laughs") can expand to gigabytes and hang QGIS, and
external entities can be used to read local files (XXE). No real LandXML export declares a DOCTYPE
or entities, so a file that does is refused.

A DOCTYPE (and with it every entity declaration) can only appear in the prolog, before the root
element. RFD streams large files with ``iterparse`` and clears elements as it goes, which keeps a
60 MB export to a fraction of a second; checking the prolog first gives the same protection as a
hardened parser without giving that up. The same approach as the LandXML Road & Terrain GIS Tools
plugin's ``safe_xml.py``, which hardens a whole-tree parser instead.
"""
from __future__ import annotations

import io
import os
import re

_PROLOG_LIMIT = 1 << 20                 # 1 MB: far more than any real prolog
_ROOT = re.compile(rb"<(?![?!])")        # the first start tag that is not <? ... ?> or <! ... >
_UNSAFE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


class UnsafeXmlError(ValueError):
    """The file declares a DOCTYPE or an entity; refused rather than parsed."""


def _head(src) -> bytes:
    if isinstance(src, (bytes, bytearray)):
        return bytes(src[:_PROLOG_LIMIT])
    if isinstance(src, str) and src.lstrip().startswith("<"):
        return src[:_PROLOG_LIMIT].encode("utf-8", "replace")
    if isinstance(src, (str, os.PathLike)):
        with open(src, "rb") as fh:
            return fh.read(_PROLOG_LIMIT)
    if isinstance(src, io.IOBase) or hasattr(src, "read"):
        pos = src.tell()
        data = src.read(_PROLOG_LIMIT)
        src.seek(pos)
        return data if isinstance(data, bytes) else data.encode("utf-8", "replace")
    return b""


def _strip_comments(b: bytes) -> bytes:
    return re.sub(rb"<!--.*?-->", b"", b, flags=re.S)


def check(src) -> None:
    """Raise UnsafeXmlError when the prolog of src (path, XML text, bytes or a binary stream) declares a
    DOCTYPE or an entity. The stream position is left where it was."""
    head = _strip_comments(_head(src))
    m = _ROOT.search(head)
    prolog = head[:m.start()] if m else head
    if _UNSAFE.search(prolog):
        raise UnsafeXmlError("Refusing to read this LandXML: it declares a DOCTYPE or XML entities, which no real "
                             "LandXML export has and which can be used to attack the parser. Re-export the file, "
                             "or check where it came from.")
