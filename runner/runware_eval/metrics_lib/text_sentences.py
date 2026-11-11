"""Sentences in the text (or in one JSON field with `field:`). For "one sentence" or "at most three": gate with `max`. Counts runs of text that end in . ! or ?; a decimal point or an abbreviation with a full stop inside a word does not count."""
import re

from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_sentences',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': 'sentences',
    'direction': '',
    'description': 'Sentences in the text (or in one JSON field with `field:`). For "one sentence" or "at most three": gate with `max`. Counts runs of text that end in . ! or ?; a decimal point or an abbreviation with a full stop inside a word does not count.',
}


def compute(p, opt):
    t = text_part(p, opt).strip()
    if not t:
        return {"value": 0.0}
    ends = re.findall(r"[.!?]+(?=[\"'”’)\]]*(?:\s|$))", t)
    return {"value": float(len(ends) + (0 if re.search(r"[.!?][\"'”’)\]]*$", t) else 1))}
