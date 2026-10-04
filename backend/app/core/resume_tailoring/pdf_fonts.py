"""Choose the font a replacement word is drawn in, so edited text matches its neighbours.

An edited line must look like the line it replaced. The best font for that is the exact one the
source PDF already embeds. Word and most exporters embed only the glyphs the document used,
though, so a replacement word can need a letter the subset never carried (the bold subset of the
CV this was built against has no "j", "R" or "U"). The fallback chain therefore is:

1. the font embedded in the source PDF, when it holds every glyph the word needs;
2. an installed copy of the same family (the original design, full glyph set), embedded as a
   subset of just the glyphs that were used;
3. a metric-compatible standard face (Times, Helvetica, Courier), which every viewer has.

Choosing per character keeps a document in its own typeface almost everywhere and degrades one
glyph at a time rather than switching the whole line to something else.

Every font here writes its own text encoding, so a drawn character reads back as itself by
construction: a space is U+0020 and a hyphen is U+002D whatever the source font's tables say.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from typing import Protocol

from fontTools import subset as ft_subset
from fontTools.ttLib import TTFont
from pypdf import PdfWriter
from reportlab.pdfbase import pdfmetrics

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

#: Installed-font search paths per family: (regular, bold, italic, bold-italic).
_SYSTEM_FONTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "times": (
        (
            "C:/Windows/Fonts/times.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        ),
        (
            "C:/Windows/Fonts/timesbd.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        ),
        (
            "C:/Windows/Fonts/timesi.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
        ),
        (
            "C:/Windows/Fonts/timesbi.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf",
        ),
    ),
    "arial": (
        (
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ),
        (
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ),
        (
            "C:/Windows/Fonts/ariali.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        ),
        (
            "C:/Windows/Fonts/arialbi.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        ),
    ),
    "calibri": (
        ("C:/Windows/Fonts/calibri.ttf", "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"),
        ("C:/Windows/Fonts/calibrib.ttf", "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"),
        ("C:/Windows/Fonts/calibrii.ttf", "/usr/share/fonts/truetype/crosextra/Carlito-Italic.ttf"),
        (
            "C:/Windows/Fonts/calibriz.ttf",
            "/usr/share/fonts/truetype/crosextra/Carlito-BoldItalic.ttf",
        ),
    ),
    "courier": (
        (
            "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ),
        (
            "C:/Windows/Fonts/courbd.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        ),
        (
            "C:/Windows/Fonts/couri.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Italic.ttf",
        ),
        (
            "C:/Windows/Fonts/courbi.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-BoldItalic.ttf",
        ),
    ),
}

#: Standard faces per generic style: (regular, bold, italic, bold-italic).
_STANDARD = {
    "serif": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "sans": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "mono": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}


_STANDARD_BY_KEY = {
    norm_key: face
    for faces in _STANDARD.values()
    for face in faces
    for norm_key in [re.sub(r"[^a-z0-9]", "", face.lower())]
}


def bare_name(font_name: str) -> str:
    """The PDF font name without its ``ABCDEF+`` subset prefix."""
    return _SUBSET_PREFIX.sub("", font_name or "")


def norm_name(font_name: str) -> str:
    """A comparison key for a font name.

    One PDF font is named differently in different places: the text layer says "CharisSIL" or
    "TimesNewRomanPSMT", the font table says "Charis SIL Regular" or "BCDEEE+TimesNewRomanPSMT".
    Subset prefix, case, spaces, punctuation and the word "regular" are dropped so the two meet;
    the style words (bold, italic) stay, so a bold face never matches a regular one.
    """
    low = re.sub(r"[^a-z0-9]", "", bare_name(font_name).lower())
    return low.replace("regular", "")


def _style_index(name: str) -> int:
    low = name.lower()
    bold = "bold" in low or low.endswith(("-bd", ",bold"))
    italic = "italic" in low or "oblique" in low
    return (1 if bold else 0) + (2 if italic else 0)


def _family_key(name: str) -> str:
    low = bare_name(name).lower()
    for key, hints in (
        ("times", ("times", "serif", "georgia", "garamond", "cambria", "palatino", "book")),
        ("arial", ("arial", "helvet", "sans", "verdana", "tahoma", "segoe", "roboto", "open")),
        ("calibri", ("calibri", "carlito")),
        ("courier", ("courier", "mono", "consolas")),
    ):
        if any(h in low for h in hints):
            return key
    return "times"


def _generic(key: str) -> str:
    return {"times": "serif", "arial": "sans", "calibri": "sans", "courier": "mono"}[key]


# --- fonts a run can be drawn in -------------------------------------------------------------


class PdfFont(Protocol):
    """What the layout and the writer need from a font."""

    kind: str  # "reused" | "system" | "standard"

    def has_glyph(self, codepoint: int) -> bool: ...
    def text_length(self, text: str, fontsize: float) -> float: ...
    def encode(self, text: str) -> bytes: ...


class StandardFont:
    """One of the 14 standard faces: not embedded, available in every viewer, WinAnsi encoded."""

    kind = "standard"

    def __init__(self, name: str) -> None:
        self.name = name

    def has_glyph(self, codepoint: int) -> bool:
        try:
            chr(codepoint).encode("cp1252")
        except UnicodeEncodeError:
            return False
        return codepoint >= 32 and not 0x7F <= codepoint < 0xA0

    def text_length(self, text: str, fontsize: float) -> float:
        return pdfmetrics.stringWidth(text, self.name, fontsize)

    def encode(self, text: str) -> bytes:
        return text.encode("cp1252")


class SystemFont:
    """An installed TrueType face, embedded as a subset of the glyphs the edits actually use."""

    kind = "system"

    def __init__(self, path: str) -> None:
        self.path = path
        self.name = os.path.basename(path)
        self.tt = TTFont(path, lazy=True)
        self._cmap: dict[int, str] = self.tt.getBestCmap() or {}
        self._order = self.tt.getGlyphOrder()
        self._gid = {n: i for i, n in enumerate(self._order)}
        self._upem = self.tt["head"].unitsPerEm
        self._hmtx = self.tt["hmtx"]
        #: character -> the CID it is drawn with. CIDs are handed out in order of first use, so the
        #: embedded subset can drop every unused glyph and renumber the rest.
        self.used: dict[str, int] = {}

    def has_glyph(self, codepoint: int) -> bool:
        return codepoint in self._cmap

    def text_length(self, text: str, fontsize: float) -> float:
        return sum(self._hmtx[self._cmap[ord(c)]][0] for c in text) / self._upem * fontsize

    def encode(self, text: str) -> bytes:
        out = bytearray()
        for ch in text:
            cid = self.used.setdefault(ch, len(self.used) + 1)
            out += cid.to_bytes(2, "big")
        return bytes(out)

    def subset_program(self) -> tuple[bytes, bytes]:
        """The font program holding only the glyphs used, and the CID -> glyph id map for it."""
        opts = ft_subset.Options()
        opts.notdef_outline = True
        opts.layout_features = []
        opts.hinting = False
        opts.name_IDs = [1, 2, 3, 4, 6]
        names = {ch: self._cmap[ord(ch)] for ch in self.used}
        font = TTFont(self.path)
        sub = ft_subset.Subsetter(opts)
        sub.populate(glyphs=sorted(set(names.values())))
        sub.subset(font)
        mapping = bytearray(2 * (max(self.used.values()) + 1))
        for ch, cid in self.used.items():
            mapping[2 * cid : 2 * cid + 2] = font.getGlyphID(names[ch]).to_bytes(2, "big")
        buf = io.BytesIO()
        font.save(buf)
        return buf.getvalue(), bytes(mapping)

    def widths(self) -> dict[int, int]:
        return {
            cid: round(self._hmtx[self._cmap[ord(ch)]][0] * 1000 / self._upem)
            for ch, cid in self.used.items()
        }


class ReusedFont:
    """A simple TrueType font already in the PDF, drawing only glyphs its subset still holds."""

    kind = "reused"

    def __init__(
        self, ref_id: int, ref: object, name: str, codes: dict[int, int], widths: dict[int, float]
    ) -> None:
        self.ref_id, self.ref, self.name = ref_id, ref, name
        self._codes = codes  # codepoint -> character code in the font
        self._widths = widths  # character code -> width in 1/1000 em

    def has_glyph(self, codepoint: int) -> bool:
        return codepoint in self._codes

    def text_length(self, text: str, fontsize: float) -> float:
        return sum(self._widths[self._codes[ord(c)]] for c in text) / 1000.0 * fontsize

    def encode(self, text: str) -> bytes:
        return bytes(self._codes[ord(c)] for c in text)


def _reusable(ref_id: int, ref: object, font: dict, name: str) -> ReusedFont | None:
    """A ReusedFont for a simple, WinAnsi-encoded, embedded TrueType font; else None.

    Only these are reused: the code that draws a character is then the plain WinAnsi code, so
    the new text extracts as exactly what it is, and the widths the viewer uses are the ones
    in the font dictionary.
    """
    try:
        if font.get("/Subtype") != "/TrueType" or font.get("/Encoding") != "/WinAnsiEncoding":
            return None
        desc = font["/FontDescriptor"].get_object()
        program = desc["/FontFile2"].get_object().get_data()
        first = int(font["/FirstChar"])
        widths = [float(w) for w in font["/Widths"]]
        tt = TTFont(io.BytesIO(program), lazy=True)
        cmap = next(
            (t.cmap for t in tt["cmap"].tables if (t.platformID, t.platEncID) == (3, 1)), None
        )
        if cmap is None:
            return None
        glyf = tt["glyf"]
    except Exception:  # an unreadable font only costs us this candidate
        return None
    codes: dict[int, int] = {}
    by_code: dict[int, float] = {}
    for code in range(first, first + len(widths)):
        width = widths[code - first]
        try:
            ch = bytes([code]).decode("cp1252")
        except UnicodeDecodeError:
            continue
        glyph = cmap.get(ord(ch))
        if glyph is None or width <= 0 or not ch.strip():
            continue
        try:
            drawn = glyf[glyph].numberOfContours != 0
        except Exception:
            drawn = False
        if drawn:
            codes[ord(ch)] = code
            by_code[code] = width
    return ReusedFont(ref_id, ref, name, codes, by_code) if codes else None


@dataclass
class FontChoice:
    """A usable font plus where it came from, so the audit can say what was substituted."""

    font: PdfFont
    source: str  # "embedded" | "system" | "base14"
    name: str


class FontResolver:
    """Resolves a (source font name, text) pair to a font that can draw that text."""

    def __init__(self, writer: PdfWriter) -> None:
        self._embedded: dict[str, list[ReusedFont]] = {}
        self._cache: dict[tuple[str, str], FontChoice | None] = {}
        self._system: dict[str, SystemFont] = {}
        self._standard: dict[str, StandardFont] = {}
        seen: set[int] = set()
        for page in writer.pages:
            fonts = (page.get("/Resources") or {}).get("/Font") or {}
            for _key, ref in fonts.items():
                font = ref.get_object()
                ident = getattr(ref, "idnum", None)
                if ident is None or ident in seen:
                    continue
                seen.add(ident)
                base = str(font.get("/BaseFont", ""))
                reused = _reusable(ident, ref, font, base)
                if reused is not None:
                    self._embedded.setdefault(norm_name(base), []).append(reused)

    @property
    def system_fonts(self) -> list[SystemFont]:
        return [f for f in self._system.values() if f.used]

    def standard(self, name: str) -> StandardFont:
        return self._standard.setdefault(name, StandardFont(name))

    def space(self, font_name: str) -> FontChoice:
        """The font a word separator is drawn in: a standard face, so it is a real U+0020."""
        generic = _generic(_family_key(font_name))
        return FontChoice(
            self.standard(_STANDARD[generic][_style_index(font_name)]), "base14", font_name
        )

    def segments(self, font_name: str, text: str) -> list[tuple[str, FontChoice]] | str:
        """Split ``text`` into runs, each drawn in the best font that has the glyphs.

        Chosen per character so a word keeps the document's own typeface wherever it can.
        Returns the reason instead when some character no available font can draw.
        """
        runs: list[tuple[str, FontChoice]] = []
        for ch in text:
            choice = self._char_choice(font_name, ch)
            if choice is None:
                return f"no available font can draw '{ch}'"
            if runs and runs[-1][1].font is choice.font:
                runs[-1] = (runs[-1][0] + ch, runs[-1][1])
            else:
                runs.append((ch, choice))
        return runs

    def _char_choice(self, font_name: str, ch: str) -> FontChoice | None:
        key = (font_name, ch)
        if key not in self._cache:
            self._cache[key] = self._resolve_char(font_name, ch)
        return self._cache[key]

    def _resolve_char(self, font_name: str, ch: str) -> FontChoice | None:
        name = bare_name(font_name)
        for font in self._embedded.get(norm_name(font_name), []):
            if font.has_glyph(ord(ch)):
                return FontChoice(font, "embedded", name)

        own = _STANDARD_BY_KEY.get(re.sub(r"[^a-z0-9]", "", name.lower()))
        if own is not None:
            # The document is set in one of the 14 standard faces: it is not embedded, and the
            # very same face is available to draw with.
            std = self.standard(own)
            return FontChoice(std, "embedded", name) if std.has_glyph(ord(ch)) else None

        family = _family_key(name)
        idx = _style_index(name)
        for path in _SYSTEM_FONTS[family][idx]:
            if os.path.exists(path):
                try:
                    font = self._system.get(path) or self._system.setdefault(path, SystemFont(path))
                except Exception:
                    continue
                if font.has_glyph(ord(ch)):
                    return FontChoice(font, "system", font.name)
        std = self.standard(_STANDARD[_generic(family)][idx])
        return FontChoice(std, "base14", name) if std.has_glyph(ord(ch)) else None
