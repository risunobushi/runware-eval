"""Character error rate of the expected text as an OCR model reads it off the output (0 = every character is there, 1 = none). Expected text: `text:` on the check or on the input; without one, the text read off the input, so the check asks whether the copy survived. Text around it does not count (see `ocr_extra_text`)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'ocr_cer',
    'trust': 'learned',
    'family': 'ocr',
    'kind': 'info',  # with the input's own text an unchanged output scores 0; with a `text:` to add it must not
    'needs': ['reference'],
    'unit': 'character error rate',
    'direction': 'lower',
    'tolerance': 0.02,  # smallest difference that counts (margin of a limit set from results)
    'description': 'Character error rate of the expected text as an OCR model reads it off the output (0 = every character is there, 1 = none). Expected text: `text:` on the check or on the input; without one, the text read off the input, so the check asks whether the copy survived. Text around it does not count (see `ocr_extra_text`).',
}


def compute(p, opt):
    region, case = opt.get("region"), bool(opt.get("case"))
    want = opt.get("text") or p.input.get("text")
    source = "given"
    if not want:
        # only what is read with confidence: a stray mark read as one letter is not copy to keep
        want = [l["text"] for l in ocr(p, "in", region, min_conf=float(opt.get("min_conf", 0.7))) if len(squash(l["text"])) > 1]
        source = "read off the input"
        if not want:
            raise ValueError("the OCR model reads no text in the input: give the expected `text:` on the check or the input")
    want = [want] if isinstance(want, str) else list(want)
    found = " ".join(l["text"] for l in ocr(p, "out", region))
    hay = squash(found, case)
    parts = [squash(w, case) for w in want]
    parts = [w for w in parts if w]
    if not parts:
        raise ValueError("the expected text is empty")
    errors = sum(text_distance(w, hay) for w in parts)
    return {"value": errors / sum(len(w) for w in parts), "expected": " | ".join(map(str, want))[:300],
            "found": found[:300], "source": source}
