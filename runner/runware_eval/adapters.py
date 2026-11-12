"""Adapters for outputs that are not a plain picture: cut-outs, masks, vector files and text.

Like the 3D and video adapters, each one makes its output look like something the rest of the runner
already knows: a picture at the input's shape (what the report, the labeling page and the image
checks use), a mask where the output has an outline of its own, and the facts only that kind of
output has.

| task type          | output            | picture (`view`)                     | outline (`masks/..._cut.png`) | facts        |
|--------------------|-------------------|--------------------------------------|-------------------------------|--------------|
| `removeBackground` | image with alpha  | the cut-out on a checkerboard        | its alpha channel             | `pair.alpha` |
| `imageMasking`     | black/white mask  | the input, dimmed outside the mask   | the mask itself               |              |
| `vectorize`        | SVG               | the SVG rendered at the input's width| none                          | `pair.svg`   |
| `caption`, `textInference` | text      | the text on a card                   | none                          | `pair.text`  |

`upscale` needs no adapter: its output is a picture, compared with the input like any other.
"""
import io
import os
import re
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from . import text as textmod

SHAPES = ("path", "rect", "circle", "ellipse", "polygon", "polyline", "line")
ARITY = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7, "z": 0}


def kind(path, task_type=None):
    """What an output file is, from its extension and the task that made it."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg":
        return "vector"
    if ext in textmod.TEXT_EXT:
        return "text"
    if task_type == "removeBackground":
        return "cutout"
    if task_type == "imageMasking":
        return "mask"
    return "image"


def _checker(w, h, cell=None):
    cell = cell or max(8, max(w, h) // 48)
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((yy // cell) + (xx // cell)) % 2 == 0)[..., None], 0.82, 0.62) * np.ones(3)


def cutout(path, view_png, mask_png):
    """A background-removal output: its alpha channel is its outline. Writes the cut-out on a
    checkerboard (the picture) and the outline as a mask. Returns its facts."""
    im = Image.open(path)
    has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    rgba = np.asarray(im.convert("RGBA")).astype(np.float64) / 255.0
    a = rgba[..., 3]
    h, w = a.shape
    comp = rgba[..., :3] * a[..., None] + _checker(w, h) * (1 - a[..., None])
    Image.fromarray((comp * 255).astype(np.uint8)).save(view_png)
    Image.fromarray(((a > 0.5) * 255).astype(np.uint8)).save(mask_png)
    return {"has_alpha": bool(has_alpha), "kept_share": float((a > 0.5).mean()),
            "soft_share": float(((a > 0.02) & (a < 0.98)).mean()), "width": w, "height": h}


def mask(path, rgb_in, view_png, mask_png):
    """A masking output: the file is the outline (white = selected). Writes the input with everything
    outside the mask dimmed (the picture) and the mask at the input's size."""
    H, W = rgb_in.shape[:2]
    m = Image.open(path).convert("L")
    native = m.size
    if m.size != (W, H):
        m = m.resize((W, H), Image.BILINEAR)
    sel = np.asarray(m) > 127
    view = rgb_in * np.where(sel, 1.0, 0.28)[..., None]
    view[sel] = view[sel] * 0.75 + np.array([0.69, 1.0, 0.62]) * 0.25  # a light green wash over what is selected
    Image.fromarray((np.clip(view, 0, 1) * 255).astype(np.uint8)).save(view_png)
    Image.fromarray((sel * 255).astype(np.uint8)).save(mask_png)
    return {"selected_share": float(sel.mean()), "width": native[0], "height": native[1]}


def svg_facts(path):
    """What a vector file is made of. `images` counts embedded bitmaps: a file with one is a picture in
    an SVG wrapper, not a vector drawing."""
    raw = open(path, "rb").read()
    facts = {"file_kb": len(raw) / 1024, "shapes": 0, "nodes": 0, "images": 0, "text_elements": 0, "colours": 0}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as err:
        return {**facts, "error": f"not valid SVG: {err}"}
    colours = set()
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower() if isinstance(el.tag, str) else ""
        if tag in SHAPES:
            facts["shapes"] += 1
        if tag == "image":
            facts["images"] += 1
        if tag == "text":
            facts["text_elements"] += 1
        if tag == "path":
            cmd = None
            for tok in re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", el.get("d") or ""):
                if tok.isalpha():
                    cmd, count = tok.lower(), 0
                    if cmd == "z":
                        continue
                elif cmd and ARITY.get(cmd):
                    count += 1
                    if count % ARITY[cmd] == 0:
                        facts["nodes"] += 1
        elif tag in ("polygon", "polyline"):
            facts["nodes"] += len(re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)", el.get("points") or "")) // 2
        elif tag in ("rect", "circle", "ellipse", "line"):
            facts["nodes"] += {"rect": 4, "line": 2}.get(tag, 4)
        style = dict(p.split(":", 1) for p in (el.get("style") or "").split(";") if ":" in p)
        for key in ("fill", "stroke", "stop-color"):
            v = (el.get(key) or style.get(key) or "").strip().lower()
            if v and v not in ("none", "transparent", "currentcolor", "inherit") and not v.startswith("url("):
                colours.add(v)
    facts["colours"] = len(colours)
    return facts


def svg(path, view_png, width):
    """A vector output: rendered on white at the input's width (resvg, shipped with the runner), so the
    image checks compare the drawing with the input. Returns the file's facts and the render's size."""
    import resvg_py
    facts = svg_facts(path)
    source = open(path, encoding="utf8", errors="replace").read()
    try:
        try:
            png = resvg_py.svg_to_bytes(svg_string=source, width=int(width), background="#ffffff")
        except ValueError:
            # seen on a Picsart file: `width="1366pt"` on the root is refused ("invalid size"). The drawing's
            # own coordinates (viewBox) are enough, so the root's width and height are left out and it is tried again
            root = re.search(r"<svg\b[^>]*>", source)
            if not (root and "viewBox" in root.group(0)):
                raise
            bare = re.sub(r"""\s(?:width|height)\s*=\s*(["']).*?\1""", "", root.group(0))
            png = resvg_py.svg_to_bytes(svg_string=source.replace(root.group(0), bare, 1), width=int(width),
                                        background="#ffffff")
            facts["render_note"] = "rendered from its viewBox: the renderer refused the root's width and height"
    except ValueError as err:
        return {**facts, "render_error": str(err)}
    im = Image.open(io.BytesIO(bytes(png))).convert("RGB")
    im.save(view_png)
    return {**facts, "width": im.width, "height": im.height}
