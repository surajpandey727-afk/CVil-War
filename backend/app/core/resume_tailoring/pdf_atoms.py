"""Turn a page into movable, self-contained pieces, and move them.

Reflowing a page means changing where things sit without redrawing them. The pieces are *atoms*:
one shown line of text, or one drawn rule or shape. Each is rewritten into a canonical, fully
self-describing form (its own graphics state, its own text matrix with the page transform baked
in), so it draws identically wherever it is placed, on any page, in any order. Different
exporters nest and share state differently (Word wraps every run in ``q ... Q``, ReportLab leaves
text in one long object); canonicalising means the reflow does not care.

Only content that can be moved without guessing is accepted. Images, shadings, inline images
and rotated or skewed transforms make :func:`split_page` refuse, and the caller leaves the
document as it is. A clip window (a table cell that clips its text) is carried by each atom drawn
under it and moves with it; a clip that is the whole page is simply dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.resume_tailoring import pdf_stream as ps

_PATH_BUILD = {"m", "l", "c", "v", "y", "h", "re"}
_PATH_PAINT = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*"}
_UNSUPPORTED = {"Do", "sh", "BI", "ID", "EI", "d0", "d1"}
_FILL = {"g", "rg", "k"}
_STROKE = {"G", "RG", "K"}
_MISC = {"w", "J", "j", "M", "d", "i", "ri"}
_ASCENT, _DESCENT = 0.9, 0.22


@dataclass
class Atom:
    """One movable piece of a page."""

    ops: list[ps.Op]
    kind: str  # "text" | "rule" | "shape"
    top: float  # of the ink, measured down from the top of the page
    bottom: float
    left: float = 0.0
    right: float = 0.0
    baseline: float | None = None
    fonts: set[str] = field(default_factory=set)
    gstates: set[str] = field(default_factory=set)
    source_page: int = 0


class Unsupported(Exception):  # noqa: N818 (a condition, not an error)
    """The page holds something the reflow cannot move safely."""


@dataclass
class _Gfx:
    ctm: ps.Matrix = ps.IDENTITY
    fill: list[ps.Op] = field(default_factory=list)
    stroke: list[ps.Op] = field(default_factory=list)
    extg: ps.Op | None = None
    misc: dict[str, ps.Op] = field(default_factory=dict)
    #: Baked clip windows in force, each as ``[path ops..., W, n]``.
    clips: list[list[ps.Op]] = field(default_factory=list)
    font: str | None = None
    size: float = 0.0
    tc: float = 0.0
    tw: float = 0.0
    tz: float = 100.0
    ts: float = 0.0
    tr: int = 0

    def copy(self) -> _Gfx:
        return _Gfx(
            self.ctm,
            list(self.fill),
            list(self.stroke),
            self.extg,
            dict(self.misc),
            list(self.clips),
            self.font,
            self.size,
            self.tc,
            self.tw,
            self.tz,
            self.ts,
            self.tr,
        )


def _uniform(m: ps.Matrix) -> bool:
    return abs(m[1]) < 1e-9 and abs(m[2]) < 1e-9 and abs(m[0] - m[3]) < 1e-9 and m[0] > 0


def _bake(op: ps.Op, m: ps.Matrix) -> list[ps.Op]:
    """A path-construction operator with the transform ``m`` applied to its coordinates."""
    v = [float(x) for x in op.operands]
    name = op.operator
    if name == "re":
        x, y = ps.apply(m, v[0], v[1])
        return [ps.op("re", x, y, v[2] * m[0], v[3] * m[3])]
    if name in ("m", "l"):
        return [ps.op(name, *ps.apply(m, v[0], v[1]))]
    if name in ("c", "v", "y"):
        pts = [ps.apply(m, v[i], v[i + 1]) for i in range(0, len(v), 2)]
        return [ps.op(name, *[c for p in pts for c in p])]
    return [op]


def _bbox(ops: list[ps.Op]) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for op in ops:
        v = [float(x) for x in op.operands]
        if op.operator == "re" and len(v) >= 4:
            xs += [v[0], v[0] + v[2]]
            ys += [v[1], v[1] + v[3]]
        elif op.operator in ("m", "l", "c", "v", "y") and len(v) >= 2:
            xs += v[0::2]
            ys += v[1::2]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def split_page(
    ops: list[ps.Op],
    fonts: dict[str, ps.FontMetrics],
    height: float,
    page_index: int,
    width: float = 612.0,
) -> list[Atom]:
    """The page's atoms in drawing order. Raises :class:`Unsupported` if anything cannot be "
    "moved."""
    interp = ps.Interpreter(ops, fonts)
    glyphs: dict[int, list[ps.Glyph]] = {}
    for g in interp.glyphs:
        glyphs.setdefault(g.op, []).append(g)

    atoms: list[Atom] = []
    gfx, stack = _Gfx(), []
    path: list[ps.Op] = []
    clip: ps.Op | None = None
    for index, op in enumerate(ops):
        name = op.operator
        if name in _UNSUPPORTED:
            raise Unsupported(f"the page uses '{name}', which cannot be moved")
        if name == "q":
            stack.append(gfx.copy())
        elif name == "Q":
            if stack:
                gfx = stack.pop()
        elif name == "cm":
            gfx.ctm = ps.mul(tuple(float(v) for v in op.operands[:6]), gfx.ctm)  # type: ignore[arg-type]
        elif name == "gs":
            gfx.extg = op
        elif name in _FILL:
            gfx.fill = [op]
        elif name in _STROKE:
            gfx.stroke = [op]
        elif name == "cs":
            gfx.fill = [op]
        elif name in ("sc", "scn"):
            gfx.fill = [*gfx.fill, op]
        elif name == "CS":
            gfx.stroke = [op]
        elif name in ("SC", "SCN"):
            gfx.stroke = [*gfx.stroke, op]
        elif name in _MISC:
            gfx.misc[name] = op
        elif name == "Tf":
            gfx.font, gfx.size = op.operands[0].value, float(op.operands[1])
        elif name == "Tc":
            gfx.tc = float(op.operands[0])
        elif name == "Tw":
            gfx.tw = float(op.operands[0])
        elif name == "Tz":
            gfx.tz = float(op.operands[0])
        elif name == "Ts":
            gfx.ts = float(op.operands[0])
        elif name == "Tr":
            gfx.tr = int(float(op.operands[0]))
        elif name in _PATH_BUILD:
            if not _uniform(gfx.ctm):
                raise Unsupported("the page draws under a rotated or skewed transform")
            path.extend(_bake(op, gfx.ctm) if name != "h" else [op])
        elif name in ("W", "W*"):
            clip = op
        elif name == "n":
            if clip is not None and path and not _covers_page(path, width, height):
                gfx.clips.append([*path, clip, ps.op("n")])
            path, clip = [], None
        elif name in _PATH_PAINT:
            if path:
                atoms.append(_path_atom(path, name, gfx, height, page_index))
            path, clip = [], None
        elif name in ps.SHOW and index in glyphs:
            atoms.append(_text_atom(op, index, glyphs[index], gfx, interp, height, page_index))
    return atoms


def _covers_page(path: list[ps.Op], width: float, height: float) -> bool:
    box = _bbox(path)
    return (
        box is not None and (box[2] - box[0]) >= 0.9 * width and (box[3] - box[1]) >= 0.9 * height
    )


def _state_ops(gfx: _Gfx, *, stroke: bool = True) -> list[ps.Op]:
    out: list[ps.Op] = []
    if gfx.extg is not None:
        out.append(gfx.extg)
    out += gfx.fill
    if stroke:
        out += gfx.stroke
    out += gfx.misc.values()
    return out


def _clip_ops(gfx: _Gfx) -> list[ps.Op]:
    return [o for group in gfx.clips for o in group]


def _gs_names(gfx: _Gfx) -> set[str]:
    return {str(gfx.extg.operands[0].value)} if gfx.extg is not None else set()


def _path_atom(path: list[ps.Op], paint: str, gfx: _Gfx, height: float, page_index: int) -> Atom:
    box = _bbox(path)
    if box is None:
        raise Unsupported("a drawn shape has no readable extent")
    scale = gfx.ctm[0]
    state = _state_ops(gfx)
    if scale != 1.0:
        state = [
            o if o.operator != "w" else ps.op("w", float(o.operands[0]) * scale) for o in state
        ]
    ops = [ps.op("q"), *_clip_ops(gfx), *state, *path, ps.op(paint), ps.op("Q")]
    thin = (box[3] - box[1]) <= 3.0 and (box[2] - box[0]) >= 40
    return Atom(
        ops,
        "rule" if thin else "shape",
        height - box[3],
        height - box[1],
        box[0],
        box[2],
        None,
        set(),
        _gs_names(gfx),
        page_index,
    )


def _show_op(op: ps.Op) -> ps.Op:
    """A ``'`` or ``"`` shows one string like ``Tj`` does (the line move and spacing are baked "
    "in)."""
    if op.operator == "TJ":
        return op
    string = op.operands[-1]
    return ps.Op("Tj", [string], ps.literal(string) + b" Tj") if isinstance(string, bytes) else op


def _text_atom(
    op: ps.Op,
    index: int,
    glyphs: list[ps.Glyph],
    gfx: _Gfx,
    interp: ps.Interpreter,
    height: float,
    page_index: int,
) -> Atom:
    start = interp.show_start.get(index)
    if start is None or gfx.font is None:
        raise Unsupported("a text run could not be located")
    tm, ctm = start
    body = [
        ps.op("q"),
        *_clip_ops(gfx),
        *_state_ops(gfx, stroke=gfx.tr in (1, 2, 5, 6)),
        ps.op("BT"),
    ]
    body.append(ps.op("Tf", ps.Name(gfx.font), gfx.size))
    for opname, value, default in (
        ("Tc", gfx.tc, 0.0),
        ("Tw", gfx.tw, 0.0),
        ("Tz", gfx.tz, 100.0),
        ("Ts", gfx.ts, 0.0),
        ("Tr", float(gfx.tr), 0.0),
    ):
        if value != default:
            body.append(ps.op(opname, value))
    body += [ps.op("Tm", *ps.mul(tm, ctm)), _show_op(op), ps.op("ET"), ps.op("Q")]
    size = max(interp.state_at[g.op][1] for g in glyphs) * (abs(ctm[3]) or 1.0)
    baseline = height - glyphs[0].y
    return Atom(
        body,
        "text",
        baseline - _ASCENT * size,
        baseline + _DESCENT * size,
        min(g.x0 for g in glyphs),
        max(g.x1 for g in glyphs),
        baseline,
        {gfx.font},
        _gs_names(gfx),
        page_index,
    )


def shifted(atom: Atom, dy_down: float) -> list[ps.Op]:
    """The atom's operators with everything moved ``dy_down`` points lower on the page."""
    if abs(dy_down) < 1e-9:
        return list(atom.ops)
    dy = -dy_down  # PDF y runs up
    out: list[ps.Op] = []
    for op in atom.ops:
        name = op.operator
        v = [float(x) for x in op.operands] if name in ("Tm", "re", "m", "l", "c", "v", "y") else []
        if name == "Tm" and len(v) >= 6:
            v[5] += dy
            out.append(ps.op("Tm", *v))
        elif name == "re" and len(v) >= 4:
            out.append(ps.op("re", v[0], v[1] + dy, v[2], v[3]))
        elif name in ("m", "l", "c", "v", "y") and v:
            out.append(ps.op(name, *[c + dy if k % 2 else c for k, c in enumerate(v)]))
        else:
            out.append(op)
    return out
