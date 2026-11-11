"""How solid the cut-out is inside the reference region, away from its edge: mean alpha, 1 = fully opaque. Below about 0.99 the subject itself was left partly see-through (the new background will show through it). Also reports the share of pixels under 90% opacity."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'alpha_opacity',
    'trust': 'deterministic',
    'family': 'signal',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'mean alpha',
    'direction': 'higher',
    'tolerance': 0.02,  # smallest difference that counts (margin of a limit set from results)
    'description': 'How solid the cut-out is inside the reference region, away from its edge: mean alpha, 1 = fully opaque. Below about 0.99 the subject itself was left partly see-through (the new background will show through it). Also reports the share of pixels under 90% opacity.',
}


def compute(p, opt):
    a = alpha(p)
    core = erode(p.region(opt.get("region", "product")), float(opt.get("edge_pct", 1.0)))
    if not core.any():
        raise ValueError("the region is too thin to have an inside away from its edge")
    return {"value": float(a[core].mean()), "see_through_share": float((a[core] < 0.9).mean())}
