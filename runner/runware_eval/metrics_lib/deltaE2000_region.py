"""Colour change inside a region (CIEDE2000; options: ignore_lightness, l_range, erode_pct). Reports mean and p95."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'deltaE2000_region',
    'trust': 'deterministic',
    'family': 'colorimetric',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'ΔE2000',
    'direction': 'lower',
    'copy_sensitive': True,
    'description': 'Colour change inside a region (CIEDE2000; options: ignore_lightness, l_range, erode_pct). Reports mean and p95.',
}


def compute(p, opt):
    spec = opt.get("region")
    sel = erode(p.region(spec) & p.region(spec, "out"), opt.get("erode_pct", 0.15))
    lo, hi = opt.get("l_range", (0, 100))
    if "l_range" in opt:
        sel &= (p.lab_in[..., 0] > lo) & (p.lab_in[..., 0] < hi) & (p.lab_out[..., 0] > lo) & (p.lab_out[..., 0] < hi)
    a, b = p.lab_in[sel], p.lab_out[sel].copy()
    if opt.get("ignore_lightness"):
        b[:, 0] = a[:, 0]
    de = deltaE_ciede2000(a, b)
    return {"value": float(de.mean()), "mean": float(de.mean()), "p95": float(np.percentile(de, 95))}
