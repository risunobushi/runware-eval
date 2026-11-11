"""Does the product keep its outline through a video? Lowest overlap (IoU) between its outline in the sample frames and in the input."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_outline_hold',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'preserve',
    'needs': ['video', 'reference', 'region'],
    'unit': 'IoU',
    'direction': 'higher',
    'tolerance': 0.02,  # smallest difference that counts (margin of a limit set from results)
    'description': 'Does the product keep its outline through a video? Lowest overlap (IoU) between its outline in the sample frames and in the input.',
}


def _fit(mask, ref):
    """The frame's outline moved and scaled onto the input outline's bounding box: shape only."""
    ys, xs = np.nonzero(mask)
    ry, rx = np.nonzero(ref)
    if not len(ys) or not len(ry):
        return mask
    cut = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
    h, w = ry.max() - ry.min() + 1, rx.max() - rx.min() + 1
    out = np.zeros_like(ref)
    out[ry.min():ry.min() + h, rx.min():rx.min() + w] = cv2.resize(cut, (w, h), interpolation=cv2.INTER_NEAREST) > 0
    return out


def compute(pair, opt):
    """The run buys an outline of the product for five frames spread over the clip. Each is compared with
    the input's `region` (default `product`). `value` is the lowest IoU, `end` the last frame's, `at_s`
    when the lowest happens. As it is, the check is for clips where the product should stay where it
    is (a relight, a locked-off shot with small motion): a camera move or a turning product lowers it
    honestly. With `align: true` each outline is first moved and scaled onto the input's bounding
    box, so only the shape is compared (a push-in passes, a product that changes shape does not)."""
    ref = pair.region(opt.get("region", "product"))
    ious, ts = [], []
    for smp in video_outlines(pair):
        m = _fit(smp["mask"], ref) if opt.get("align") else smp["mask"]
        ious.append(float((ref & m).sum() / max(1, (ref | m).sum())))
        ts.append(smp["t"])
    low = int(np.argmin(ious))
    return {"value": ious[low], "end": ious[-1], "at_s": ts[low], "series": series(ious, times=ts)}
