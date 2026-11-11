"""Does the text match the regular expression in `pattern:` (searched anywhere, case-insensitive unless `case: true`)? For a fixed format: a SKU, a date, one sentence."""
import re

from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_regex',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': '1 / 0',
    'direction': 'higher',
    'description': 'Does the text match the regular expression in `pattern:` (searched anywhere, case-insensitive unless `case: true`)? For a fixed format: a SKU, a date, one sentence.',
}


def compute(p, opt):
    if not opt.get("pattern"):
        raise KeyError("`pattern:` is missing on the check")
    flags = re.S | (0 if opt.get("case") else re.I)
    return {"value": 1.0 if re.search(opt["pattern"], text_part(p, opt), flags) else 0.0}
