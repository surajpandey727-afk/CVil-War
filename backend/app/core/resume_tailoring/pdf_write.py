"""Put new text and fonts into a page without touching anything else on it.

The writing half of the in-place editor: it registers fonts on a page, turns laid-out runs into
drawing operators, and builds the font objects (a subset of an installed TrueType face, embedded
with a ToUnicode map so the text reads back as exactly what was drawn).
"""

from __future__ import annotations

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    IndirectObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from app.core.resume_tailoring import pdf_stream as ps
from app.core.resume_tailoring.pdf_fonts import PdfFont, ReusedFont, StandardFont, SystemFont

#: Text-state parameters reset around inserted text, so it is drawn plainly whatever the
#: neighbouring text had set (spacing, scaling, rise, render mode).
_RESET = (("Tc", 0), ("Tw", 0), ("Tz", 100), ("Ts", 0), ("Tr", 0))


def _flate(writer: PdfWriter, data: bytes) -> IndirectObject:
    stream = DecodedStreamObject()
    stream.set_data(data)
    return writer._add_object(stream.flate_encode())


class FontRegistry:
    """Gives each font a resource name on each page that draws with it."""

    def __init__(self, writer: PdfWriter) -> None:
        self.writer = writer
        self._standard: dict[str, IndirectObject] = {}
        self._system: dict[str, tuple[str, SystemFont]] = {}
        self._pages_using: dict[str, set[int]] = {}
        self._counter = 0

    def _fonts_dict(self, page) -> DictionaryObject:
        res = page.get("/Resources")
        if res is None:
            res = DictionaryObject()
            page[NameObject("/Resources")] = res
        res = res.get_object()
        fonts = res.get("/Font")
        if fonts is None:
            fonts = DictionaryObject()
            res[NameObject("/Font")] = fonts
        return fonts.get_object()

    def name_for(self, page_index: int, font: PdfFont) -> str:
        page = self.writer.pages[page_index]
        fonts = self._fonts_dict(page)
        if isinstance(font, ReusedFont):
            for key, ref in fonts.items():
                if getattr(ref, "idnum", None) == font.ref_id:
                    return key.lstrip("/")
            return self._add(fonts, font.ref)
        if isinstance(font, StandardFont):
            ref = self._standard.get(font.name)
            if ref is None:
                ref = self._standard[font.name] = self.writer._add_object(
                    DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/" + font.name),
                            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                        }
                    )
                )
            return self._existing(fonts, ref) or self._add(fonts, ref)
        assert isinstance(font, SystemFont)
        if font.path not in self._system:
            self._counter += 1
            self._system[font.path] = (f"CVEmb{self._counter}", font)
        name = self._system[font.path][0]
        self._pages_using.setdefault(font.path, set()).add(page_index)
        return name

    def _existing(self, fonts: DictionaryObject, ref: IndirectObject) -> str | None:
        for key, value in fonts.items():
            if getattr(value, "idnum", None) == ref.idnum:
                return key.lstrip("/")
        return None

    def _add(self, fonts: DictionaryObject, ref: IndirectObject) -> str:
        self._counter += 1
        name = f"CVFnt{self._counter}"
        fonts[NameObject("/" + name)] = ref
        return name

    def finalize(self) -> None:
        """Create the embedded font objects and attach them to the pages that use them."""
        for path, (name, font) in self._system.items():
            ref = self._embed(font)
            for index in self._pages_using.get(path, set()):
                self._fonts_dict(self.writer.pages[index])[NameObject("/" + name)] = ref

    def _embed(self, font: SystemFont) -> IndirectObject:
        w = self.writer
        tt = font.tt
        ps_name = "CVEMBD+" + "".join(
            c for c in (font.tt["name"].getDebugName(6) or "Font") if c.isalnum() or c == "-"
        )
        head, hhea, os2 = tt["head"], tt["hhea"], tt["OS/2"]
        scale = 1000.0 / head.unitsPerEm
        program, cid_to_gid = font.subset_program()
        descriptor = w._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/FontDescriptor"),
                    NameObject("/FontName"): NameObject("/" + ps_name),
                    NameObject("/Flags"): NumberObject(32),
                    NameObject("/FontBBox"): ArrayObject(
                        FloatObject(round(v * scale, 1))
                        for v in (head.xMin, head.yMin, head.xMax, head.yMax)
                    ),
                    NameObject("/ItalicAngle"): FloatObject(round(tt["post"].italicAngle, 2)),
                    NameObject("/Ascent"): NumberObject(round(hhea.ascent * scale)),
                    NameObject("/Descent"): NumberObject(round(hhea.descent * scale)),
                    NameObject("/CapHeight"): NumberObject(
                        round(getattr(os2, "sCapHeight", 0) * scale)
                        or round(hhea.ascent * scale * 0.7)
                    ),
                    NameObject("/StemV"): NumberObject(80),
                    NameObject("/FontFile2"): _flate(w, program),
                }
            )
        )
        widths = ArrayObject()
        for cid, width in sorted(font.widths().items()):
            widths.extend([NumberObject(cid), ArrayObject([NumberObject(width)])])
        cid = w._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/CIDFontType2"),
                    NameObject("/BaseFont"): NameObject("/" + ps_name),
                    NameObject("/CIDSystemInfo"): DictionaryObject(
                        {
                            NameObject("/Registry"): TextStringObject("Adobe"),
                            NameObject("/Ordering"): TextStringObject("Identity"),
                            NameObject("/Supplement"): NumberObject(0),
                        }
                    ),
                    NameObject("/FontDescriptor"): descriptor,
                    NameObject("/DW"): NumberObject(0),
                    NameObject("/W"): widths,
                    NameObject("/CIDToGIDMap"): _flate(w, cid_to_gid),
                }
            )
        )
        return w._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type0"),
                    NameObject("/BaseFont"): NameObject("/" + ps_name),
                    NameObject("/Encoding"): NameObject("/Identity-H"),
                    NameObject("/DescendantFonts"): ArrayObject([cid]),
                    NameObject("/ToUnicode"): _flate(w, _to_unicode(font.used)),
                }
            )
        )


def _to_unicode(used: dict[str, int]) -> bytes:
    rows = [
        f"<{cid:04X}> <{ord(ch):04X}>"
        if ord(ch) < 0x10000
        else f"<{cid:04X}> <{ch.encode('utf-16-be').hex().upper()}>"
        for ch, cid in sorted(used.items(), key=lambda kv: kv[1])
    ]
    blocks = [
        "\n".join([f"{len(rows[i : i + 100])} beginbfchar", *rows[i : i + 100], "endbfchar"])
        for i in range(0, len(rows), 100)
    ]
    return (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        + "\n".join(blocks)
        + "\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode("ascii")


def run_ops(
    runs, ctm: ps.Matrix, page_height: float, page_index: int, fonts: FontRegistry
) -> list[ps.Op]:
    """Drawing operators for ``runs``, written in the space the surrounding content is in.

    ``runs`` carry page coordinates (x right, y measured down from the top). The content stream
    around the insertion point may have a transform in force, so positions are mapped back
    through its inverse; text drawn with it lands exactly where the layout put it.
    """
    inverse = ps.invert(ctm)
    if inverse is None or not runs:
        return []
    out: list[ps.Op] = [ps.op("q"), *(ps.op(name, value) for name, value in _RESET)]
    linear = inverse[:4]
    last_color: int | None = None
    for run in runs:
        name = fonts.name_for(page_index, run.choice.font)
        px, py = ps.apply(inverse, run.x, page_height - run.y)
        if run.color != last_color:
            r, g, b = (
                ((run.color >> 16) & 255) / 255,
                ((run.color >> 8) & 255) / 255,
                (run.color & 255) / 255,
            )
            out.append(ps.op("rg", r, g, b))
            last_color = run.color
        encoded = run.choice.font.encode(run.text)
        shown = (
            ps.hex_string(encoded)
            if isinstance(run.choice.font, SystemFont)
            else ps.literal(encoded)
        )
        out += [
            ps.op("BT"),
            ps.op("Tf", ps.Name(name), run.size),
            ps.op("Tm", *linear, px, py),
            ps.Op("Tj", [encoded], shown + b" Tj"),
            ps.op("ET"),
        ]
    out.append(ps.op("Q"))
    return out
