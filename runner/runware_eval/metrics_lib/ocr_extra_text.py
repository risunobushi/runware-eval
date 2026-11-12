"""Words an OCR model reads in the output that are neither in the input nor in the expected `text:`: taglines, credits or gibberish nobody asked for. The words are listed next to the count."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'ocr_extra_text',
    'trust': 'learned',
    'family': 'ocr',
    'kind': 'preserve',
    'needs': ['reference'],
    'unit': 'unexpected words',
    'direction': 'lower',
    'tolerance': 0.5,  # smallest difference that counts (margin of a limit set from results)
    'description': 'Words an OCR model reads in the output that are neither in the input nor in the expected `text:`: taglines, credits or gibberish nobody asked for. The words are listed next to the count.',
}


def compute(p, opt):
    region = opt.get("region")
    want = opt.get("text") or p.input.get("text") or []
    want = [want] if isinstance(want, str) else list(want)
    allowed = squash(" ".join([l["text"] for l in ocr(p, "in", region)] + [str(w) for w in want]))
    seen, extra = set(), []
    for line in ocr(p, "out", region, min_conf=float(opt.get("min_conf", 0.6))):
        for w in words(line["text"]):
            # a word counts as known when it is in the allowed text give or take one character in five
            if len(w) < 2 or w in seen or text_distance(w, allowed) <= len(w) // 5:
                continue
            seen.add(w)
            extra.append(w)
    return {"value": float(len(extra)), "extra": ", ".join(extra)[:300]}
