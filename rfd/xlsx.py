"""A small .xlsx writer and reader for the workbooks Road Furniture Designer makes and reads back.

Writing: sheets of values and formulas, bold / italic / coloured fonts, solid fills, alignment, column
widths, frozen panes, Excel Tables and list data validation. The names and calls follow openpyxl
(Workbook, Font, PatternFill, Alignment, Table, TableStyleInfo, DataValidation, get_column_letter) for
the parts RFD uses, so the writers read the same.

Reading: load_workbook() gives cell values (shared and inline strings, numbers, booleans, cached
formula results) of any workbook Excel saves. Values set on a loaded workbook are written back into
the original file's sheet XML, leaving everything else in the file (styles, tables, validation,
other sheets) as it was.

No third-party library: the plugin ships without bundled packages. XML is parsed with the standard
library's expat, which does not fetch external entities.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import tempfile
import zipfile
from xml.parsers import expat

# ------------------------------------------------------------------ cells and styles
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def esc(s) -> str:
    s = _ILLEGAL.sub("", str(s))
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def get_column_letter(i: int) -> str:
    s = ""
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def column_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch.upper()) - 64
    return n


def split_ref(ref: str):
    m = re.match(r"\$?([A-Za-z]+)\$?(\d+)$", ref)
    return int(m.group(2)), column_index(m.group(1))


class Font:
    def __init__(self, bold=False, italic=False, size=None, color=None):
        self.bold, self.italic, self.size, self.color = bold, italic, size, color

    def key(self):
        return (self.bold, self.italic, self.size, self.color)


class PatternFill:
    def __init__(self, fill_type="solid", fgColor=None):
        self.fill_type, self.fgColor = fill_type, fgColor

    def key(self):
        return (self.fill_type, self.fgColor)


class Alignment:
    def __init__(self, horizontal=None, vertical=None, wrap_text=False):
        self.horizontal, self.vertical, self.wrap_text = horizontal, vertical, wrap_text

    def key(self):
        return (self.horizontal, self.vertical, self.wrap_text)


class Cell:
    __slots__ = ("row", "column", "value", "font", "fill", "alignment")

    def __init__(self, row, column, value=None):
        self.row, self.column, self.value = row, column, value
        self.font = self.fill = self.alignment = None

    @property
    def column_letter(self):
        return get_column_letter(self.column)

    @property
    def coordinate(self):
        return f"{get_column_letter(self.column)}{self.row}"


class _Dim:
    def __init__(self):
        self.width = None


class _Dims(dict):
    def __missing__(self, key):
        self[key] = _Dim()
        return self[key]


class TableStyleInfo:
    def __init__(self, name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False,
                 showFirstColumn=False, showLastColumn=False):
        self.name, self.showRowStripes, self.showColumnStripes = name, showRowStripes, showColumnStripes
        self.showFirstColumn, self.showLastColumn = showFirstColumn, showLastColumn


class Table:
    def __init__(self, displayName, ref):
        self.displayName, self.ref = displayName, ref
        self.tableStyleInfo = TableStyleInfo()


class DataValidation:
    def __init__(self, type="list", formula1="", allow_blank=True):
        self.type, self.formula1, self.allow_blank = type, formula1, allow_blank
        self.ranges = []

    def add(self, sqref):
        self.ranges.append(sqref)


class Worksheet:
    def __init__(self, wb, title):
        self.parent, self.title = wb, title
        self._cells = {}
        self.column_dimensions = _Dims()
        self.freeze_panes = None
        self.tables = []
        self.validations = []

    def cell(self, row, column, value=None):
        c = self._cells.get((row, column))
        if c is None:
            c = self._cells[(row, column)] = Cell(row, column)
        if value is not None:
            c.value = value
        return c

    def __getitem__(self, key):
        if isinstance(key, int):                       # ws[1]: the cells of row 1
            return [self._cells[k] for k in sorted(self._cells) if k[0] == key]
        r, c = split_ref(key)
        return self.cell(r, c)

    def __setitem__(self, key, value):
        self[key].value = value

    @property
    def max_row(self):
        return max((r for r, _c in self._cells), default=0)

    @property
    def max_column(self):
        return max((c for _r, c in self._cells), default=0)

    def append(self, values):
        r = self.max_row + 1
        for i, v in enumerate(values, start=1):
            if v is not None:
                self.cell(r, i, v)
        if not values or all(v is None for v in values):
            self.cell(r, 1)

    def add_table(self, t):
        self.tables.append(t)

    def add_data_validation(self, dv):
        self.validations.append(dv)


class Workbook:
    def __init__(self):
        self.worksheets = [Worksheet(self, "Sheet")]

    @property
    def active(self):
        return self.worksheets[0]

    @property
    def sheetnames(self):
        return [w.title for w in self.worksheets]

    def __getitem__(self, name):
        return next(w for w in self.worksheets if w.title == name)

    def create_sheet(self, title, index=None):
        ws = Worksheet(self, title)
        if index is None:
            self.worksheets.append(ws)
        else:
            self.worksheets.insert(index, ws)
        return ws

    def save(self, path):
        _write(self, path)


# ------------------------------------------------------------------ writing
_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_ODR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT = "application/vnd.openxmlformats-officedocument"
_HDR = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _argb(c):
    c = (c or "000000").lstrip("#").upper()
    return c if len(c) == 8 else "FF" + c


class _Styles:
    def __init__(self):
        self.fonts = [None]            # index 0: the default font
        self.fills = [None, "gray"]    # 0 none, 1 gray125 (required by Excel)
        self.xfs = [(0, 0, None)]

    def index(self, cell):
        if cell.font is None and cell.fill is None and cell.alignment is None:
            return 0
        fk = cell.font.key() if cell.font else None
        if fk is None:
            fi = 0
        else:
            if fk not in self.fonts:
                self.fonts.append(fk)
            fi = self.fonts.index(fk)
        pk = cell.fill.key() if cell.fill else None
        if pk is None:
            pi = 0
        else:
            if pk not in self.fills:
                self.fills.append(pk)
            pi = self.fills.index(pk)
        ak = cell.alignment.key() if cell.alignment else None
        xf = (fi, pi, ak)
        if xf not in self.xfs:
            self.xfs.append(xf)
        return self.xfs.index(xf)

    def xml(self):
        fonts = []
        for f in self.fonts:
            if f is None:
                fonts.append('<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>')
                continue
            bold, italic, size, color = f
            fonts.append("<font>" + ("<b/>" if bold else "") + ("<i/>" if italic else "")
                         + f'<sz val="{size or 11}"/>' + (f'<color rgb="{_argb(color)}"/>' if color else "")
                         + '<name val="Calibri"/><family val="2"/></font>')
        fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>']
        for p in self.fills[2:]:
            fills.append(f'<fill><patternFill patternType="{p[0]}"><fgColor rgb="{_argb(p[1])}"/>'
                         '<bgColor indexed="64"/></patternFill></fill>')
        xfs = []
        for fi, pi, ak in self.xfs:
            attrs = f'numFmtId="0" fontId="{fi}" fillId="{pi}" borderId="0" xfId="0"'
            if fi:
                attrs += ' applyFont="1"'
            if pi:
                attrs += ' applyFill="1"'
            if ak:
                h, v, w = ak
                al = "<alignment" + (f' horizontal="{h}"' if h else "") + (f' vertical="{v}"' if v else "") \
                     + (' wrapText="1"' if w else "") + "/>"
                xfs.append(f'<xf {attrs} applyAlignment="1">{al}</xf>')
            else:
                xfs.append(f"<xf {attrs}/>")
        return (_HDR + f'<styleSheet {_NS}><fonts count="{len(fonts)}">' + "".join(fonts) + "</fonts>"
                f'<fills count="{len(fills)}">' + "".join(fills) + "</fills>"
                '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(xfs)}">' + "".join(xfs) + "</cellXfs>"
                '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                "</styleSheet>")


def _cell_xml(c, styles, sst):
    ref = c.coordinate
    s = styles.index(c)
    sa = f' s="{s}"' if s else ""
    v = c.value
    if v is None:
        return f'<c r="{ref}"{sa}/>' if s else ""
    if isinstance(v, bool):
        return f'<c r="{ref}"{sa} t="b"><v>{int(v)}</v></c>'
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            return f'<c r="{ref}"{sa} t="inlineStr"><is><t>{esc(v)}</t></is></c>'
        return f'<c r="{ref}"{sa}><v>{repr(v) if isinstance(v, float) else v}</v></c>'
    if isinstance(v, (_dt.datetime, _dt.date)):
        v = v.isoformat(sep=" ") if isinstance(v, _dt.datetime) else v.isoformat()
    v = str(v)
    if v.startswith("=") and len(v) > 1:
        return f'<c r="{ref}"{sa}><f>{esc(v[1:])}</f></c>'
    if v not in sst:
        sst[v] = len(sst)
    return f'<c r="{ref}"{sa} t="s"><v>{sst[v]}</v></c>'


def _sheet_xml(ws, styles, sst, table_rids):
    rows = {}
    for (r, c), cell in ws._cells.items():
        rows.setdefault(r, []).append(cell)
    parts = [_HDR, f"<worksheet {_NS} {_RNS}>"]
    if ws._cells:
        parts.append(f'<dimension ref="A1:{get_column_letter(max(ws.max_column, 1))}{max(ws.max_row, 1)}"/>')
    fp = ws.freeze_panes
    if fp is not None:
        ref = fp.coordinate if isinstance(fp, Cell) else str(fp)
        r, c = split_ref(ref)
        xs, ys = c - 1, r - 1
        pane = "bottomRight" if xs and ys else ("bottomLeft" if ys else "topRight")
        attrs = (f' xSplit="{xs}"' if xs else "") + (f' ySplit="{ys}"' if ys else "")
        parts.append(f'<sheetViews><sheetView workbookViewId="0"><pane{attrs} topLeftCell="{ref}" '
                     f'activePane="{pane}" state="frozen"/><selection pane="{pane}" activeCell="{ref}" '
                     f'sqref="{ref}"/></sheetView></sheetViews>')
    widths = sorted((column_index(k), d.width) for k, d in ws.column_dimensions.items() if d.width)
    if widths:
        parts.append("<cols>" + "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in widths)
                     + "</cols>")
    parts.append("<sheetData>")
    for r in sorted(rows):
        cells = "".join(_cell_xml(c, styles, sst) for c in sorted(rows[r], key=lambda c: c.column))
        parts.append(f'<row r="{r}">{cells}</row>')
    parts.append("</sheetData>")
    if ws.validations:
        parts.append(f'<dataValidations count="{len(ws.validations)}">')
        for dv in ws.validations:
            f1 = dv.formula1[1:] if dv.formula1.startswith("=") else dv.formula1
            parts.append(f'<dataValidation type="{dv.type}" allowBlank="{int(bool(dv.allow_blank))}" '
                         f'showInputMessage="1" showErrorMessage="1" sqref="{" ".join(dv.ranges)}">'
                         f"<formula1>{esc(f1)}</formula1></dataValidation>")
        parts.append("</dataValidations>")
    parts.append('<pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0.5" footer="0.5"/>')
    if table_rids:
        parts.append(f'<tableParts count="{len(table_rids)}">'
                     + "".join(f'<tablePart r:id="{rid}"/>' for rid in table_rids) + "</tableParts>")
    parts.append("</worksheet>")
    return "".join(parts)


def _table_xml(t, tid, ws):
    a, b = t.ref.split(":")
    r0, c0 = split_ref(a)
    _r1, c1 = split_ref(b)
    names, seen = [], set()
    for c in range(c0, c1 + 1):
        v = ws.cell(r0, c).value
        n = str(v) if v not in (None, "") else f"Column{c - c0 + 1}"
        base, k = n, 2
        while n in seen:
            n, k = f"{base}{k}", k + 1
        seen.add(n)
        names.append(n)
        if v in (None, ""):
            ws.cell(r0, c, n)
    si = t.tableStyleInfo
    cols = "".join(f'<tableColumn id="{i}" name="{esc(n)}"/>' for i, n in enumerate(names, start=1))
    return (_HDR + f'<table {_NS} id="{tid}" name="{esc(t.displayName)}" displayName="{esc(t.displayName)}" '
            f'ref="{t.ref}"><autoFilter ref="{t.ref}"/><tableColumns count="{len(names)}">{cols}</tableColumns>'
            f'<tableStyleInfo name="{si.name}" showFirstColumn="{int(si.showFirstColumn)}" '
            f'showLastColumn="{int(si.showLastColumn)}" showRowStripes="{int(si.showRowStripes)}" '
            f'showColumnStripes="{int(si.showColumnStripes)}"/></table>')


def _write(wb, path):
    styles, sst = _Styles(), {}
    sheets, tables, rels = [], [], {}
    tid = 0
    for n, ws in enumerate(wb.worksheets, start=1):
        rids = []
        srels = []
        for t in ws.tables:
            tid += 1
            rid = f"rId{len(rids) + 1}"
            rids.append(rid)
            tables.append((tid, _table_xml(t, tid, ws)))
            srels.append(f'<Relationship Id="{rid}" Type="{_ODR}/table" Target="../tables/table{tid}.xml"/>')
        sheets.append(_sheet_xml(ws, styles, sst, rids))
        if srels:
            rels[n] = (_HDR + f'<Relationships xmlns="{_PKG}">' + "".join(srels) + "</Relationships>")
    ct = [f'<Override PartName="/xl/worksheets/sheet{n}.xml" ContentType="{_CT}.spreadsheetml.worksheet+xml"/>'
          for n in range(1, len(sheets) + 1)]
    ct += [f'<Override PartName="/xl/tables/table{i}.xml" ContentType="{_CT}.spreadsheetml.table+xml"/>'
           for i, _x in tables]
    content_types = (_HDR + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     f'<Override PartName="/xl/workbook.xml" ContentType="{_CT}.spreadsheetml.sheet.main+xml"/>'
                     f'<Override PartName="/xl/styles.xml" ContentType="{_CT}.spreadsheetml.styles+xml"/>'
                     f'<Override PartName="/xl/sharedStrings.xml" ContentType="{_CT}.spreadsheetml.sharedStrings+xml"/>'
                     '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                     f'<Override PartName="/docProps/app.xml" ContentType="{_CT}.extended-properties+xml"/>'
                     + "".join(ct) + "</Types>")
    root_rels = (_HDR + f'<Relationships xmlns="{_PKG}">'
                 f'<Relationship Id="rId1" Type="{_ODR}/officeDocument" Target="xl/workbook.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                 f'<Relationship Id="rId3" Type="{_ODR}/extended-properties" Target="docProps/app.xml"/>'
                 "</Relationships>")
    wb_xml = (_HDR + f"<workbook {_NS} {_RNS}><bookViews><workbookView/></bookViews><sheets>"
              + "".join(f'<sheet name="{esc(ws.title)}" sheetId="{n}" r:id="rId{n}"/>'
                        for n, ws in enumerate(wb.worksheets, start=1))
              + "</sheets></workbook>")
    k = len(wb.worksheets)
    wb_rels = (_HDR + f'<Relationships xmlns="{_PKG}">'
               + "".join(f'<Relationship Id="rId{n}" Type="{_ODR}/worksheet" Target="worksheets/sheet{n}.xml"/>'
                         for n in range(1, k + 1))
               + f'<Relationship Id="rId{k + 1}" Type="{_ODR}/styles" Target="styles.xml"/>'
               + f'<Relationship Id="rId{k + 2}" Type="{_ODR}/sharedStrings" Target="sharedStrings.xml"/>'
               + "</Relationships>")
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (_HDR + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>Road Furniture Designer</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
    app = (_HDR + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           "<Application>Road Furniture Designer</Application></Properties>")
    strings = sorted(sst, key=sst.get)
    sst_xml = (_HDR + f'<sst {_NS} count="{len(strings)}" uniqueCount="{len(strings)}">'
               + "".join(f'<si><t xml:space="preserve">{esc(s)}</t></si>' for s in strings) + "</sst>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("xl/workbook.xml", wb_xml)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles.xml())
        z.writestr("xl/sharedStrings.xml", sst_xml)
        for n, x in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{n}.xml", x)
            if n in rels:
                z.writestr(f"xl/worksheets/_rels/sheet{n}.xml.rels", rels[n])
        for i, x in tables:
            z.writestr(f"xl/tables/table{i}.xml", x)


# ------------------------------------------------------------------ a minimal XML tree (expat)
class Node:
    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.children, self.text = tag, attrs, [], ""

    def local(self):
        return self.tag.split(":")[-1]

    def find(self, local):
        return next((c for c in self.children if isinstance(c, Node) and c.local() == local), None)

    def findall(self, local):
        return [c for c in self.children if isinstance(c, Node) and c.local() == local]

    def itertext(self):
        out = [self.text]
        for c in self.children:
            out.append(c.itertext() if isinstance(c, Node) else "")
        return "".join(out)


def parse_xml(data: bytes) -> Node:
    """Element tree of an XML document (qualified names kept as written, text kept in .text of
    leaf elements and as str children elsewhere)."""
    p = expat.ParserCreate()
    root = Node("#document", {})
    stack = [root]

    def start(tag, attrs):
        n = Node(tag, dict(attrs))
        stack[-1].children.append(n)
        stack.append(n)

    def end(_tag):
        n = stack.pop()
        if not any(isinstance(c, Node) for c in n.children):
            n.text = "".join(c for c in n.children if isinstance(c, str))
            n.children = []

    def chars(data):
        stack[-1].children.append(data)

    p.ordered_attributes = False
    p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = start, end, chars
    p.Parse(data, True)
    return next(c for c in root.children if isinstance(c, Node))


def to_xml(n: Node) -> str:
    attrs = "".join(f' {k}="{esc(v)}"' for k, v in n.attrs.items())
    if not n.children and not n.text:
        return f"<{n.tag}{attrs}/>"
    inner = esc(n.text) if not n.children else "".join(to_xml(c) if isinstance(c, Node) else esc(c)
                                                        for c in n.children)
    return f"<{n.tag}{attrs}>{inner}</{n.tag}>"


# ------------------------------------------------------------------ reading and editing
def _target(base, target):
    if target.startswith("/"):
        return target.lstrip("/")
    return os.path.normpath(os.path.join(os.path.dirname(base), target)).replace("\\", "/")


class LoadedSheet:
    def __init__(self, book, title, part, root):
        self.book, self.title, self.part, self.root = book, title, part, root
        self.values = {}
        sd = root.find("sheetData")
        for row in (sd.findall("row") if sd is not None else []):
            for c in row.findall("c"):
                r, col = split_ref(c.attrs["r"])
                self.values[(r, col)] = book._cell_value(c)
        self.edits = {}

    @property
    def max_row(self):
        return max((r for r, _c in self.values), default=0)

    def cell(self, row, column, value=None):
        if value is not None:
            self.values[(row, column)] = value
            self.edits[(row, column)] = value
        return _ValueRef(self, row, column)

    def __getitem__(self, ref):
        r, c = split_ref(ref)
        return _ValueRef(self, r, c)

    def iter_rows(self, min_row=1, values_only=True):
        mc = max((c for _r, c in self.values), default=0)
        for r in range(min_row, self.max_row + 1):
            yield tuple(self.values.get((r, c)) for c in range(1, mc + 1))


class _ValueRef:
    def __init__(self, sheet, r, c):
        self.sheet, self.row, self.column = sheet, r, c

    @property
    def value(self):
        return self.sheet.values.get((self.row, self.column))

    @property
    def column_letter(self):
        return get_column_letter(self.column)


class LoadedWorkbook:
    def __init__(self, path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            self._shared = []
            if "xl/sharedStrings.xml" in names:
                for si in parse_xml(z.read("xl/sharedStrings.xml")).findall("si"):
                    self._shared.append(si.itertext() if si.children else si.text)
            wbx = parse_xml(z.read("xl/workbook.xml"))
            rels = parse_xml(z.read("xl/_rels/workbook.xml.rels"))
            rid = {r.attrs["Id"]: _target("xl/workbook.xml", r.attrs["Target"]) for r in rels.findall("Relationship")}
            self.sheets = {}
            for s in wbx.find("sheets").findall("sheet"):
                key = next(k for k in s.attrs if k.endswith(":id"))
                part = rid[s.attrs[key]]
                self.sheets[s.attrs["name"]] = LoadedSheet(self, s.attrs["name"], part, parse_xml(z.read(part)))

    @property
    def sheetnames(self):
        return list(self.sheets)

    def __getitem__(self, name):
        return self.sheets[name]

    def _cell_value(self, c):
        t = c.attrs.get("t", "n")
        v = c.find("v")
        if t == "inlineStr":
            i = c.find("is")
            return i.itertext() if i is not None and i.children else (i.text if i is not None else "")
        if v is None:
            return None
        raw = v.text
        if t == "s":
            return self._shared[int(raw)]
        if t == "b":
            return raw == "1"
        if t in ("str", "e"):
            return raw
        try:
            f = float(raw)
            return int(f) if f.is_integer() and "." not in raw and "E" not in raw.upper() else f
        except ValueError:
            return raw

    def save(self, path):
        """Write the edits into the sheet XML; every other part of the file is copied unchanged."""
        parts = {s.part: s for s in self.sheets.values() if s.edits}
        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(os.path.abspath(path)) or None)
        os.close(fd)
        with zipfile.ZipFile(self.path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename in parts:
                    s = parts[item.filename]
                    _apply_edits(s.root, s.edits)
                    data = (_HDR + to_xml(s.root)).encode("utf-8")
                zout.writestr(item, data)
        shutil.move(tmp, path)
        self.path = path


def _apply_edits(root: Node, edits: dict):
    sd = root.find("sheetData")
    rows = {int(r.attrs["r"]): r for r in sd.findall("row")}
    for (r, col), val in sorted(edits.items()):
        row = rows.get(r)
        if row is None:
            row = Node(sd.tag.replace("sheetData", "row"), {"r": str(r)})
            rows[r] = row
            later = [i for i, n in enumerate(sd.children) if isinstance(n, Node) and int(n.attrs.get("r", 0)) > r]
            sd.children.insert(later[0] if later else len(sd.children), row)
            row.attrs.pop("spans", None)
        ref = f"{get_column_letter(col)}{r}"
        cell = next((c for c in row.findall("c") if c.attrs.get("r") == ref), None)
        ctag = row.tag.replace("row", "c")
        if cell is None:
            cell = Node(ctag, {"r": ref})
            later = [i for i, n in enumerate(row.children)
                     if isinstance(n, Node) and split_ref(n.attrs.get("r", "A1"))[1] > col]
            row.children.insert(later[0] if later else len(row.children), cell)
            row.attrs.pop("spans", None)
        style = cell.attrs.get("s")
        cell.attrs = {"r": ref}
        if style:
            cell.attrs["s"] = style
        p = ctag[:-1]                                    # namespace prefix, if the file uses one
        if isinstance(val, bool):
            cell.attrs["t"] = "b"
            cell.children = [Node(p + "v", {})]
            cell.children[0].text = str(int(val))
        elif isinstance(val, (int, float)):
            cell.children = [Node(p + "v", {})]
            cell.children[0].text = repr(val) if isinstance(val, float) else str(val)
        else:
            cell.attrs["t"] = "inlineStr"
            t = Node(p + "t", {"xml:space": "preserve"})
            t.text = str(val)
            isn = Node(p + "is", {})
            isn.children = [t]
            cell.children = [isn]
        cell.text = ""


def load_workbook(path) -> LoadedWorkbook:
    return LoadedWorkbook(path)
