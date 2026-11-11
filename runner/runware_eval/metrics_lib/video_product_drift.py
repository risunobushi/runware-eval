"""Is it still the same product later in the video? Largest change in the colour make-up of the product, frame outline against the input's (0 = same colours, 1 = nothing in common)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_product_drift',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'preserve',
    'needs': ['video', 'reference', 'region'],
    'unit': 'histogram distance',
    'direction': 'lower',
    'description': "Is it still the same product later in the video? Largest change in the colour make-up of the product, frame outline against the input's (0 = same colours, 1 = nothing in common).",
}


def _hist(rgb, mask, ab_only):
    lab = cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2LAB)
    m = mask.astype(np.uint8)
    if ab_only:
        h = cv2.calcHist([lab], [1, 2], m, [24, 24], [0, 256, 0, 256])
    else:
        h = cv2.calcHist([lab], [0, 1, 2], m, [8, 12, 12], [0, 256] * 3)
    return cv2.normalize(h, None, 1.0, 0.0, cv2.NORM_L1).astype(np.float32)


def compute(pair, opt):
    """The product is read inside its own outline in each of the five sample frames (so it may move,
    turn or be re-framed) and reduced to a colour histogram in CIELAB, which is compared with the
    product's histogram in the input (Bhattacharyya distance). A product that turns shows other sides, so
    some change is honest; one that is recoloured, swaps its material or turns into another object
    moves much further. `value` is the largest distance, `end` the last frame's, `first` the first
    frame's (the floor: what a re-encode of the input scores), `delta_e` the largest CIEDE2000 distance
    between mean colours. With `ignore_lightness: true` only hue and chroma count (for briefs that change
    the light). It says nothing about shape or lettering: pair it with `video_outline_hold` and a judge."""
    spec = opt.get("region", "product")
    ab = bool(opt.get("ignore_lightness"))
    ref_mask = erode(pair.region(spec), opt.get("erode_pct", 0.3))
    if not ref_mask.any():
        raise ValueError("the region is empty")
    ref = _hist(pair.rgb_in, ref_mask, ab)
    ref_mean = pair.lab_in[ref_mask].mean(axis=0)
    dist, de, ts = [], [], []
    for smp in video_outlines(pair):
        m = erode(smp["mask"], opt.get("erode_pct", 0.3))
        ts.append(smp["t"])
        if not m.any():  # the product is gone from this frame: nothing in common
            dist.append(1.0)
            de.append(float("nan"))
            continue
        dist.append(float(cv2.compareHist(ref, _hist(smp["rgb"], m, ab), cv2.HISTCMP_BHATTACHARYYA)))
        mean = rgb2lab(smp["rgb"])[m].mean(axis=0)
        if ab:
            mean[0] = ref_mean[0]
        de.append(float(deltaE_ciede2000(ref_mean[None], mean[None])[0]))
    hi = int(np.argmax(dist))
    return {"value": dist[hi], "end": dist[-1], "first": dist[0], "at_s": ts[hi],
            "delta_e": float(np.nanmax(de)) if not all(np.isnan(de)) else float("nan"),
            "series": series(dist, times=ts)}
