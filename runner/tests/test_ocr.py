"""The OCR checks: the expected copy is read off the output, and words nobody asked for are counted."""
import sys
from types import SimpleNamespace

import cv2
import numpy as np

from runware_eval import catalog
from runware_eval.metric_api import squash, text_distance

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def card(*lines):
    """Black lettering on white, one (text, y, scale) per line."""
    img = np.full((600, 1400, 3), 255, np.uint8)
    for text, y, scale in lines:
        cv2.putText(img, text, (60, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), int(scale * 2))
    return img.astype(np.float64) / 255.0


def pair(rgb_in, rgb_out, **inp):
    box = np.zeros(rgb_in.shape[:2], bool)
    box[:300] = True
    return SimpleNamespace(rgb_in=rgb_in, rgb_out=rgb_out, input=inp, text=None,
                           region=lambda spec, side="in": box)


reg = catalog.load()
cer, extra = reg["ocr_cer"]["compute"], reg["ocr_extra_text"]["compute"]
check("distance: a string that is in the text scores 0, whatever surrounds it",
      text_distance(squash("Made in Italy"), squash("NEW! made  in italy since 1921")) == 0)
check("distance: one wrong letter is one edit", text_distance("runware", "xx runvare yy") == 1)
check("distance: nothing like it costs the whole string", text_distance("abc", "") == 3)

logo = card(("RUNWARE", 180, 4.0), ("Made in Italy", 420, 2.5))
same = cer(pair(logo, logo), {})
check("an unchanged picture keeps its copy: error rate 0, read off the input", same["value"] == 0 and same["source"] == "read off the input", same)
garbled = card(("RUNVVARF", 180, 4.0), ("Made in Italy", 420, 2.5))
g = cer(pair(logo, garbled), {})
check("garbled lettering raises the error rate", 0.1 < g["value"] < 0.6, g)
gone = cer(pair(logo, card()), {})
check("copy that is gone scores 1", gone["value"] == 1.0, gone)
check("an expected text on the check is what is looked for", cer(pair(card(), logo), {"text": "Made in Italy"})["value"] == 0
      and cer(pair(card(), logo), {"text": "Hecho en Mexico"})["value"] > 0.5)
check("an expected text on the input works the same", cer(pair(card(), logo, text=["RUNWARE", "Made in Italy"]), {})["value"] == 0)
check("a region limits what is read", cer(pair(logo, logo), {"region": "top", "text": "Made in Italy"})["value"] > 0.5
      and cer(pair(logo, logo), {"region": "top", "text": "RUNWARE"})["value"] == 0)
try:
    cer(pair(card(), logo), {})
    check("no text in the input and none given: the check does not run", False)
except ValueError:
    check("no text in the input and none given: the check does not run", True)

check("an unchanged picture has no extra words", extra(pair(logo, logo), {})["value"] == 0)
added = card(("RUNWARE", 180, 4.0), ("Made in Italy", 420, 2.5), ("Premium Quality", 540, 2.0))
e = extra(pair(logo, added), {})
check("words that were not in the input are counted and named", e["value"] == 2 and "premium" in e["extra"], e)
check("words of the expected text are not extra", extra(pair(logo, added), {"text": "Premium Quality"})["value"] == 0)
check("both checks state a direction and a smallest difference, so the first full run can set their limit",
      all(reg[m]["meta"].get("direction") == "lower" and reg[m]["meta"].get("tolerance") for m in ("ocr_cer", "ocr_extra_text")))

print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
sys.exit(1 if FAILED else 0)
