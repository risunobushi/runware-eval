"""How much moves in a video: mean optical flow, in percent of the frame diagonal per second. A still clip scores about 0. It says how much motion there is, not how good it is, so more is not better and it does not place recipes. Its limit is its own: under 0.5 a clip reads as a still. A bench whose brief asks for more (or less) movement states `min` or `max`."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_motion',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'change',
    'needs': ['video'],
    'unit': '% of diagonal / s',
    'direction': '',  # how much, not how good: no place, and no limit from the other recipes' results
    'limit': {'min': 0.5},  # the metric's own: what separates a clip that moves from a still
    'limit_from': 'under 0.5 % of the frame diagonal per second a clip reads as a still',
    'description': 'How much moves in a video: mean optical flow, in percent of the frame diagonal per second. A still clip scores about 0. It says how much motion there is, not how good it is, so more is not better and it does not place recipes. Its limit is its own: under 0.5 a clip reads as a still. A bench whose brief asks for more (or less) movement states `min` or `max`.',
}


def compute(pair, opt):
    """Dense optical flow (Farneback) between consecutive analysis frames. `value` is the mean over the
    clip; `peak` is the fastest moment. Use `min` to reject clips that barely move and `max` to reject
    ones that move too much. Optional `region` (an input region, e.g. product) limits where flow is read;
    it only makes sense while the subject stays roughly where it was in the input."""
    v = video(pair)
    flows, g = video_flow(pair)
    if not flows:
        return {"value": float("nan")}
    h, w = g[0].shape
    sel = None
    if opt.get("region"):
        sel = cv2.resize(pair.region(opt["region"]).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
    per = []
    for flow in flows:
        mag = np.hypot(flow[..., 0], flow[..., 1])
        per.append(float(mag[sel].mean() if sel is not None and sel.any() else mag.mean()))
    scale = v["analysis_fps"] / np.hypot(w, h) * 100
    return {"value": float(np.mean(per) * scale), "peak": float(np.max(per) * scale),
            "series": series(np.array(per) * scale, v["analysis_fps"], start=1)}
