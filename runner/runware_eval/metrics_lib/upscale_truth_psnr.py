"""Pixel error against the full-size original the input was shrunk from (the input's `original:` file), as PSNR in dB: higher is closer. Strict about every pixel, so a sharper but slightly different texture scores below a blurry one: read it next to upscale_truth_ssim and upscale_detail_gain."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'upscale_truth_psnr',
    'trust': 'deterministic',
    'family': 'signal',
    'kind': 'info',
    'needs': ['reference'],
    'unit': 'dB',
    'direction': 'higher',
    'description': "Pixel error against the full-size original the input was shrunk from (the input's `original:` file), as PSNR in dB: higher is closer. Strict about every pixel, so a sharper but slightly different texture scores below a blurry one: read it next to upscale_truth_ssim and upscale_detail_gain.",
}


def compute(p, opt):
    truth, out, m = original(p, opt.get("region"))
    def psnr(rgb):
        mse = float(((truth[m].astype(np.float64) - rgb[m].astype(np.float64)) ** 2).mean())
        return 99.0 if mse == 0 else float(10 * np.log10(255.0 ** 2 / mse))
    value, plain = psnr(out), psnr(plain_resize(p, (truth.shape[1], truth.shape[0])))
    return {"value": value, "plain_resize": plain, "over_plain_resize": value - plain,
            "compared_at": f"{truth.shape[1]}x{truth.shape[0]}"}
