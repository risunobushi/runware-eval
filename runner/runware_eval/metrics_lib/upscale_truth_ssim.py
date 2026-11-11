"""How close the upscaled picture is to the full-size original the input was shrunk from (the input's `original:` file), at the original's size: SSIM of luminance, 1 = identical. Also reports what a plain resize of the input scores (`plain_resize`) and the difference: below 0, the upscaler did worse than no upscaler. The only upscale check that tells recovered detail from invented detail."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'upscale_truth_ssim',
    'trust': 'deterministic',
    'family': 'structural',
    'kind': 'info',
    'needs': ['reference'],
    'unit': 'SSIM',
    'direction': 'higher',
    'tolerance': 0.02,  # smallest difference that counts (margin of a limit set from results)
    'description': "How close the upscaled picture is to the full-size original the input was shrunk from (the input's `original:` file), at the original's size: SSIM of luminance, 1 = identical. Also reports what a plain resize of the input scores (`plain_resize`) and the difference: below 0, the upscaler did worse than no upscaler. The only upscale check that tells recovered detail from invented detail.",
}


def compute(p, opt):
    truth, out, m = original(p, opt.get("region"))
    grey = lambda rgb: cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ssim = lambda rgb: float(structural_similarity(grey(truth), grey(rgb), data_range=255, full=True)[1][m].mean())
    value, plain = ssim(out), ssim(plain_resize(p, (truth.shape[1], truth.shape[0])))
    return {"value": value, "plain_resize": plain, "over_plain_resize": value - plain,
            "compared_at": f"{truth.shape[1]}x{truth.shape[0]}"}
