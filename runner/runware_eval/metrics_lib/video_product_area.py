"""Does the product stay in the picture? Its smallest area in the sample frames of a video, relative to its area in the input (1.0 = same size)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_product_area',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'info',
    'needs': ['video', 'reference', 'region'],
    'unit': '× input area',
    'description': 'Does the product stay in the picture? Its smallest area in the sample frames of a video, relative to its area in the input (1.0 = same size).',
}


def compute(pair, opt):
    """Area of the product's outline in each of the five sample frames over its area in the input.
    `value` is the smallest ratio (near 0: the product left the frame or dissolved), `largest` the
    biggest (well above 1: a push-in, or something else was taken for the product), `pieces` the most
    separate pieces the outline had in any frame (above 1: it broke apart or a second object appeared).
    A turning product changes its area honestly, so it has no better direction: gate it from both sides
    with what the brief allows (e.g. `min: 0.5, max: 2`)."""
    ref = max(1, int(pair.region(opt.get("region", "product")).sum()))
    ratios, ts, pieces = [], [], 1
    for smp in video_outlines(pair):
        ratios.append(float(smp["mask"].sum() / ref))
        ts.append(smp["t"])
        n, _, stats, _ = cv2.connectedComponentsWithStats(smp["mask"].astype(np.uint8), connectivity=8)
        pieces = max(pieces, int((stats[1:, cv2.CC_STAT_AREA] >= 0.01 * max(1, smp["mask"].sum())).sum()) if n > 1 else 0)
    low = int(np.argmin(ratios))
    return {"value": ratios[low], "largest": float(max(ratios)), "pieces": pieces, "at_s": ts[low],
            "series": series(ratios, times=ts)}
