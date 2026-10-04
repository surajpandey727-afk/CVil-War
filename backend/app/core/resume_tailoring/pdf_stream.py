"""Read and rewrite a page's content stream, so text can be removed from the file for real.

Covering old text with a white box leaves it in the file, and a screen reader, a copy-paste or an
ATS still reads it. Removing it means editing the drawing operators themselves, which is what
this module does, at glyph level:

* :func:`parse` splits a content stream into operations and keeps each one's exact source bytes,
  so everything that is not touched is written back byte for byte;
* :class:`Interpreter` walks the operations tracking the text and graphics state (matrix, font,
  size, spacing) and reports where every glyph lands on the page;
* :func:`remove_glyphs` drops chosen glyphs from the show-text operators and widens the gap
  they leave, so the text after them stays exactly where it was.

Only the text operators are interpreted. Paths, images and everything else pass through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reportlab.pdfbase import pdfmetrics

_WS = b" \t\r\n\f\x00"
_DELIM = b"()<>[]{}/%"
_NUMBER = re.compile(rb"^[+-]?(\d+\.?\d*|\.\d+)$")
_ESCAPES = {
    ord("n"): 10,
    ord("r"): 13,
    ord("t"): 9,
    ord("b"): 8,
    ord("f"): 12,
    ord("("): 40,
    ord(")"): 41,
    ord("\\"): 92,
}
_INLINE_END = re.compile(rb"\sEI(?=[\s\x00]|$)")
_STANDARD_FACES = {
    "times-roman",
    "times-bold",
    "times-italic",
    "times-bolditalic",
    "helvetica",
    "helvetica-bold",
    "helvetica-oblique",
    "helvetica-boldoblique",
    "courier",
    "courier-bold",
    "courier-oblique",
    "courier-boldoblique",
    "symbol",
    "zapfdingbats",
}

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class Name:
    value: str


@dataclass
class Op:
    operator: str
    operands: list
    raw: bytes


# --- tokenising --------------------------------------------------------------------------------


def _skip(data: bytes, pos: int) -> int:
    n = len(data)
    while pos < n:
        if data[pos] in _WS:
            pos += 1
        elif data[pos] == 0x25:  # % comment
            while pos < n and data[pos] not in b"\r\n":
                pos += 1
        else:
            break
    return pos


def _string(data: bytes, pos: int) -> tuple[bytes, int]:
    """A literal string starting at the "(" at ``pos``; returns (bytes, position after ")")."""
    out = bytearray()
    depth = 1
    pos += 1
    n = len(data)
    while pos < n and depth:
        c = data[pos]
        if c == 0x5C and pos + 1 < n:  # backslash
            nxt = data[pos + 1]
            if 0x30 <= nxt <= 0x37:
                end = pos + 1
                while end < n and end < pos + 4 and 0x30 <= data[end] <= 0x37:
                    end += 1
                out.append(int(data[pos + 1 : end], 8) & 0xFF)
                pos = end
                continue
            if nxt in b"\r\n":
                pos += 2 + (1 if nxt == 13 and pos + 2 < n and data[pos + 2] == 10 else 0)
                continue
            out.append(_ESCAPES.get(nxt, nxt))
            pos += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if not depth:
                pos += 1
                break
        out.append(c)
        pos += 1
    return bytes(out), pos


def _hex(data: bytes, pos: int) -> tuple[bytes, int]:
    end = data.index(b">", pos)
    digits = re.sub(rb"[^0-9A-Fa-f]", b"", data[pos + 1 : end])
    if len(digits) % 2:
        digits += b"0"
    return bytes.fromhex(digits.decode()), end + 1


def _value(data: bytes, pos: int):
    """One operand starting at ``pos`` (already past whitespace); returns (value, new pos) or "
    "None."""
    c = data[pos]
    if c == 0x28:
        return _string(data, pos)
    if c == 0x2F:  # name
        end = pos + 1
        while end < len(data) and data[end] not in _WS and data[end] not in _DELIM:
            end += 1
        return Name(data[pos + 1 : end].decode("latin-1")), end
    if c == 0x3C:
        if data[pos : pos + 2] == b"<<":
            depth, end = 1, pos + 2
            while end < len(data) and depth:
                if data[end : end + 2] == b"<<":
                    depth, end = depth + 1, end + 2
                elif data[end : end + 2] == b">>":
                    depth, end = depth - 1, end + 2
                else:
                    end += 1
            return data[pos:end], end
        return _hex(data, pos)
    if c in b"+-.0123456789":
        end = pos + 1
        while end < len(data) and data[end] not in _WS and data[end] not in _DELIM:
            end += 1
        word = data[pos:end]
        return (float(word), end) if _NUMBER.match(word) else None
    if c == 0x5B:
        items: list = []
        pos += 1
        while True:
            pos = _skip(data, pos)
            if pos >= len(data):
                return items, pos
            if data[pos] == 0x5D:
                return items, pos + 1
            got = _value(data, pos)
            if got is None:
                pos += 1
                continue
            items.append(got[0])
            pos = got[1]
    return None


def parse(data: bytes) -> list[Op]:
    """Split a content stream into operations, each remembering its exact source bytes."""
    ops: list[Op] = []
    pos, n = 0, len(data)
    operands: list = []
    start = -1
    while True:
        pos = _skip(data, pos)
        if pos >= n:
            break
        if start < 0:
            start = pos
        got = _value(data, pos) if data[pos] not in b"]){}>" else None
        if got is not None:
            operands.append(got[0])
            pos = got[1]
            continue
        end = pos
        while end < n and data[end] not in _WS and data[end] not in _DELIM:
            end += 1
        if end == pos:  # a stray delimiter: skip it rather than loop forever
            pos += 1
            continue
        word = data[pos:end]
        if _NUMBER.match(word):
            operands.append(float(word))
            pos = end
            continue
        if word in (b"true", b"false", b"null"):
            operands.append({b"true": True, b"false": False, b"null": None}[word])
            pos = end
            continue
        if word == b"BI":
            image_end = _inline_image_end(data, end)
            ops.append(Op("BI", [], data[start:image_end]))
            pos, operands, start = image_end, [], -1
            continue
        ops.append(Op(word.decode("latin-1"), operands, data[start:end]))
        pos, operands, start = end, [], -1
    return ops


def _inline_image_end(data: bytes, pos: int) -> int:
    marker = re.compile(rb"\sID[\s]").search(data, pos)
    if not marker:
        return len(data)
    found = _INLINE_END.search(data, marker.end())
    return found.end() if found else len(data)


def join(ops: list[Op]) -> bytes:
    return b"\n".join(op.raw for op in ops) + b"\n"


# --- writing -----------------------------------------------------------------------------------


def _num(value: float) -> bytes:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return (text if text not in ("", "-", "-0") else "0").encode()


def literal(data: bytes) -> bytes:
    out = bytearray(b"(")
    for byte in data:
        if byte in (0x28, 0x29, 0x5C):
            out += b"\\" + bytes([byte])
        elif byte in (10, 13):
            out += b"\\n" if byte == 10 else b"\\r"
        else:
            out.append(byte)
    return bytes(out) + b")"


def hex_string(data: bytes) -> bytes:
    return b"<" + data.hex().upper().encode() + b">"


def op(operator: str, *operands: object) -> Op:
    """Build an operation from Python values (numbers, Names, bytes strings, lists)."""

    def enc(value: object) -> bytes:
        if isinstance(value, Name):
            return b"/" + value.value.encode("latin-1")
        if isinstance(value, bytes):
            return literal(value)
        if isinstance(value, list):
            return b"[" + b" ".join(enc(v) for v in value) + b"]"
        return _num(float(value))  # type: ignore[arg-type]

    raw = b" ".join([*(enc(v) for v in operands), operator.encode("latin-1")])
    return Op(operator, list(operands), raw)


# --- matrices ----------------------------------------------------------------------------------


def mul(a: Matrix, b: Matrix) -> Matrix:
    """``a`` applied first, then ``b`` (PDF row-vector convention)."""
    return (
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    )


def invert(m: Matrix) -> Matrix | None:
    det = m[0] * m[3] - m[1] * m[2]
    if abs(det) < 1e-12:
        return None
    a, b, c, d = m[3] / det, -m[1] / det, -m[2] / det, m[0] / det
    return (a, b, c, d, -(m[4] * a + m[5] * c), -(m[4] * b + m[5] * d))


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    return x * m[0] + y * m[2] + m[4], x * m[1] + y * m[3] + m[5]


# --- fonts as the interpreter needs them -----------------------------------------------------


@dataclass
class FontMetrics:
    """How wide each code of a font is and how many bytes make a code."""

    two_byte: bool = False
    vertical: bool = False
    default: float = 500.0
    widths: dict[int, float] = field(default_factory=dict)
    standard: str | None = None

    def width(self, code: int) -> float:
        if code in self.widths:
            return self.widths[code]
        if self.standard and 32 <= code < 256:
            try:
                return pdfmetrics.stringWidth(
                    bytes([code]).decode("cp1252", "replace"), self.standard, 1000.0
                )
            except Exception:
                return self.default
        return self.default


_STANDARD_CANON = {
    name.replace("-", "").lower(): name
    for name in (
        "Times-Roman",
        "Times-Bold",
        "Times-Italic",
        "Times-BoldItalic",
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-Oblique",
        "Helvetica-BoldOblique",
        "Courier",
        "Courier-Bold",
        "Courier-Oblique",
        "Courier-BoldOblique",
        "Symbol",
        "ZapfDingbats",
    )
}


def metrics_for(font: dict) -> FontMetrics:
    """Build :class:`FontMetrics` from a PDF font dictionary (pypdf object)."""
    sub = str(font.get("/Subtype", ""))
    if sub == "/Type0":
        enc = str(font.get("/Encoding", ""))
        m = FontMetrics(two_byte=True, vertical=enc.endswith("-V"))
        try:
            desc = font["/DescendantFonts"][0].get_object()
            m.default = float(desc.get("/DW", 1000))
            w = [x.get_object() if hasattr(x, "get_object") else x for x in desc.get("/W", [])]
            i = 0
            while i < len(w):
                first = int(w[i])
                nxt = w[i + 1]
                if isinstance(nxt, list):
                    for k, val in enumerate(nxt):
                        m.widths[first + k] = float(val)
                    i += 2
                else:
                    for cid in range(first, int(nxt) + 1):
                        m.widths[cid] = float(w[i + 2])
                    i += 3
        except Exception:
            pass
        return m
    m = FontMetrics()
    try:
        first = int(font.get("/FirstChar", 0))
        for k, val in enumerate(font.get("/Widths", [])):
            m.widths[first + k] = float(val.get_object() if hasattr(val, "get_object") else val)
        desc = font.get("/FontDescriptor")
        if desc is not None:
            m.default = float(desc.get_object().get("/MissingWidth", 0))
    except Exception:
        pass
    base = re.sub(r"^[A-Z]{6}\+", "", str(font.get("/BaseFont", ""))).lstrip("/")
    if not m.widths:
        m.standard = _STANDARD_CANON.get(base.replace("-", "").lower())
        m.default = 500.0
    return m


# --- interpreting ------------------------------------------------------------------------------


@dataclass
class Glyph:
    """One glyph shown by a text operator, located on the page (PDF user space, y up)."""

    op: int
    elem: int  # index within the operator's array
    start: int  # byte offset within that string
    nbytes: int
    code: int
    x0: float
    x1: float
    y: float  # baseline
    advance: float  # text-space distance the pen moved, Tc and Tw included, Th applied


SHOW = ("Tj", "TJ", "'", '"')


class Interpreter:
    """Walks the operations and reports where each glyph lands. Everything else is skipped."""

    def __init__(self, ops: list[Op], fonts: dict[str, FontMetrics]) -> None:
        self.ops = ops
        self.fonts = fonts
        self.glyphs: list[Glyph] = []
        #: CTM in force after each operation (so new content can be placed in the right space)
        self.ctm_after: list[Matrix] = []
        #: (font, size, horizontal scale) in force at each show operation
        self.state_at: dict[int, tuple[FontMetrics, float, float]] = {}
        #: (text matrix, CTM) in force when each show operation began drawing
        self.show_start: dict[int, tuple[Matrix, Matrix]] = {}
        self._run()

    def _run(self) -> None:
        ctm, stack = IDENTITY, []
        tm = tlm = IDENTITY
        font: FontMetrics | None = None
        size = tc = tw = tl = rise = 0.0
        th = 1.0
        for index, op_ in enumerate(self.ops):
            o, a = op_.operator, op_.operands
            try:
                if o == "q":
                    stack.append((ctm, font, size, tc, tw, th, tl, rise))
                elif o == "Q" and stack:
                    ctm, font, size, tc, tw, th, tl, rise = stack.pop()
                elif o == "cm":
                    ctm = mul(tuple(float(v) for v in a[:6]), ctm)  # type: ignore[arg-type]
                elif o == "BT":
                    tm = tlm = IDENTITY
                elif o == "Tf":
                    font, size = self.fonts.get(a[0].value), float(a[1])
                elif o == "Tc":
                    tc = float(a[0])
                elif o == "Tw":
                    tw = float(a[0])
                elif o == "Tz":
                    th = float(a[0]) / 100.0
                elif o == "TL":
                    tl = float(a[0])
                elif o == "Ts":
                    rise = float(a[0])
                elif o == "Td":
                    tlm = mul((1, 0, 0, 1, float(a[0]), float(a[1])), tlm)
                    tm = tlm
                elif o == "TD":
                    tl = -float(a[1])
                    tlm = mul((1, 0, 0, 1, float(a[0]), float(a[1])), tlm)
                    tm = tlm
                elif o == "Tm":
                    tm = tlm = tuple(float(v) for v in a[:6])  # type: ignore[assignment]
                elif o == "T*":
                    tlm = mul((1, 0, 0, 1, 0, -tl), tlm)
                    tm = tlm
                elif o in SHOW and font is not None:
                    if o in ("'", '"'):
                        tlm = mul((1, 0, 0, 1, 0, -tl), tlm)
                        tm = tlm
                        if o == '"':
                            tw, tc = float(a[0]), float(a[1])
                    elems = a[-1] if o == "TJ" else [a[-1]]
                    self.show_start[index] = (tm, ctm)
                    tm = self._show(index, elems, tm, ctm, font, size, tc, tw, th, rise)
                    self.state_at[index] = (font, size, th)
            except (IndexError, TypeError, ValueError, AttributeError):
                pass  # an operator we cannot read costs us position tracking, nothing more
            self.ctm_after.append(ctm)

    def _show(self, index, elems, tm, ctm, font, size, tc, tw, th, rise) -> Matrix:
        for e, elem in enumerate(elems):
            if isinstance(elem, (int, float)):
                tm = mul((1, 0, 0, 1, -float(elem) / 1000.0 * size * th, 0), tm)
                continue
            if not isinstance(elem, bytes):
                continue
            step = 2 if font.two_byte else 1
            for k in range(0, len(elem) - step + 1, step):
                code = int.from_bytes(elem[k : k + step], "big")
                w0 = font.width(code) / 1000.0 * size
                adv = (w0 + tc + (tw if step == 1 and code == 32 else 0.0)) * th
                full = mul(tm, ctm)
                x0, y = apply(full, 0.0, rise)
                x1, _ = apply(full, w0 * th, rise)
                self.glyphs.append(Glyph(index, e, k, step, code, x0, x1, y, adv))
                tm = mul((1, 0, 0, 1, adv, 0), tm)
        return tm

    def block_end(self, index: int) -> int | None:
        """Index of the ET that closes the text object holding operation ``index``."""
        for k in range(index, len(self.ops)):
            if self.ops[k].operator == "ET":
                return k
            if self.ops[k].operator == "BT" and k > index:
                return None
        return None


# --- removing ----------------------------------------------------------------------------------


def _tj(parts: list, two_byte: bool) -> Op:
    items = [
        (hex_string(p) if two_byte else literal(p)) if isinstance(p, bytes) else _num(p)
        for p in parts
    ]
    return Op("TJ", [parts], b"[" + b" ".join(items) + b"] TJ")


def remove_glyphs(ops: list[Op], interp: Interpreter, doomed: set[int]) -> list[Op | None]:
    """Copy of ``ops`` with the glyphs at ``doomed`` (indices into ``interp.glyphs``) removed.

    A removed glyph's advance is replaced by an equal gap, so the glyphs after it do not move.
    An operation left with nothing visible is dropped when nothing after it in the text object
    depends on where it ended. Returns the new list, positionally aligned with ``ops``
    (None marks a dropped operation).
    """
    by_op: dict[int, list[tuple[int, Glyph]]] = {}
    for gi, glyph in enumerate(interp.glyphs):
        by_op.setdefault(glyph.op, []).append((gi, glyph))
    out: list[Op | None] = list(ops)
    for index, members in by_op.items():
        if not any(gi in doomed for gi, _ in members):
            continue
        o = ops[index]
        font, size, th = interp.state_at[index]
        elems = o.operands[-1] if o.operator == "TJ" else [o.operands[-1]]
        parts: list = []
        gap = 0.0
        flat = {(g.elem, g.start): (gi, g) for gi, g in members}
        for e, elem in enumerate(elems):
            if isinstance(elem, (int, float)):
                parts.append(float(elem))
                continue
            keep = bytearray()
            for k in range(0, len(elem), 2 if font.two_byte else 1):
                hit = flat.get((e, k))
                if hit and hit[0] in doomed:
                    if keep:
                        parts.append(bytes(keep))
                        keep = bytearray()
                    gap += hit[1].advance
                    continue
                if gap and size:
                    parts.append(-gap / (size * th) * 1000.0)
                    gap = 0.0
                keep += elem[k : k + (2 if font.two_byte else 1)]
            if keep:
                parts.append(bytes(keep))
        if gap and size:
            parts.append(-gap / (size * th) * 1000.0)
        merged: list = []
        for p in parts:
            if isinstance(p, float) and merged and isinstance(merged[-1], float):
                merged[-1] += p
            else:
                merged.append(p)
        has_text = any(isinstance(p, bytes) for p in merged)
        if not has_text and not _position_needed(ops, index):
            out[index] = None
            continue
        pre: list[Op] = []
        if o.operator in ("'", '"'):
            pre.append(Op("T*", [], b"T*"))
            if o.operator == '"':
                pre.append(op("Tw", o.operands[0]))
                pre.append(op("Tc", o.operands[1]))
        out[index] = (
            _tj(merged, font.two_byte)
            if not pre
            else Op(
                "TJ", [merged], b"\n".join([p.raw for p in pre] + [_tj(merged, font.two_byte).raw])
            )
        )
    return out


def _position_needed(ops: list[Op], index: int) -> bool:
    """Whether a later show operator in the same text object continues from where this ended."""
    for k in range(index + 1, len(ops)):
        name = ops[k].operator
        if name in ("ET", "BT", "Tm", "Td", "TD", "T*"):
            return False
        if name in SHOW:
            return True
    return False
