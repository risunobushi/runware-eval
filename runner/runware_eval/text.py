"""Text in a bench: text outputs (`caption`, `textInference`) and text inputs (a prompt or document per file).

A text output is saved as `<input>__<recipe>__s<seed>.txt`. The text checks read the text itself; the
report shows it in full and, where a picture is needed (gallery, labeling), as a card: the text drawn
on a plain canvas. A text input (`inputs: [{ path: in/brief.txt }]`) is never uploaded: `$input`
resolves to its content.
"""
import os
import re
import textwrap

from PIL import Image, ImageDraw, ImageFont

TEXT_EXT = (".txt", ".md")
CARD = (1024, 768)


def is_text(path):
    return os.path.splitext(path)[1].lower() in TEXT_EXT


def read(path):
    return open(path, encoding="utf8", errors="replace").read()


THINK = re.compile(r"<(think|thinking|reasoning)>(.*?)(?:</\1>|\Z)", re.S | re.I)
FENCE = re.compile(r"\A\s*```[\w-]*[ \t]*\r?\n(.*?)\r?\n?```\s*\Z", re.S)


def reasoning(text):
    """The reasoning a model left in its answer (`<think>...</think>` blocks), joined; "" when there is none."""
    return "\n".join(m.group(2).strip() for m in THINK.finditer(text or ""))


def answer(text):
    """The text without reasoning blocks: what the model meant as its answer."""
    return THINK.sub("", text or "").strip()


def unfence(text):
    """(text without a Markdown code fence around the whole of it, whether there was one)."""
    m = FENCE.match(text or "")
    return (m.group(1).strip(), True) if m else ((text or "").strip(), False)


def words(text):
    """Lower-case words of a text (letters and digits, with inner apostrophes and hyphens kept)."""
    return re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", (text or "").lower())


def card(text, size=CARD, px=22):
    """The text drawn on a canvas: what stands in for a text where the report needs a picture.
    Text that does not fit is cut, and the card says how many words were left out."""
    W, H = size
    px = max(12, round(px * min(W, H) / 768))
    font = ImageFont.load_default(size=px)
    pad, line_h = round(px * 1.6), round(px * 1.45)
    per_line = max(8, int((W - 2 * pad) / (font.getlength("n") or px / 2)))
    lines = []
    for para in (text or "").replace("\r", "").split("\n"):
        lines += textwrap.wrap(para, per_line) or [""]
    room = max(1, (H - 2 * pad) // line_h)
    left_out = 0
    if len(lines) > room:
        left_out = len(words(" ".join(lines[room - 1:])))
        lines = lines[:room - 1] + [f"[... {left_out} more words: see the report's text panel]"]
    img = Image.new("RGB", (W, H), (250, 250, 247))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((pad, pad + i * line_h), line, fill=(60, 60, 60) if left_out and i == len(lines) - 1 else (20, 20, 20),
               font=font)
    return img
