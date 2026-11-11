"""Word overlap between the text and the input's `reference:` text (F1 of shared words, 0 to 1). It rewards the same words, not the same meaning: a good paraphrase scores low, so pair it with a judge."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_reference_f1',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output', 'reference'],
    'unit': 'F1',
    'direction': 'higher',
    'description': "Word overlap between the text and the input's `reference:` text (F1 of shared words, 0 to 1). It rewards the same words, not the same meaning: a good paraphrase scores low, so pair it with a judge.",
}


def compute(p, opt):
    ref = p.input.get("reference")
    if not ref:
        raise KeyError("this input has no `reference:` text")
    got, want = words(text_part(p, opt)), words(str(ref))
    if not got or not want:
        return {"value": 0.0}
    left, shared = list(want), 0
    for w in got:
        if w in left:
            left.remove(w)
            shared += 1
    if not shared:
        return {"value": 0.0}
    precision, recall = shared / len(got), shared / len(want)
    return {"value": 2 * precision * recall / (precision + recall), "precision": precision, "recall": recall}
