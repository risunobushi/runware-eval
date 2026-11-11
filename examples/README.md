# Examples

## `metrics/`: metrics written for one bench

The runner ships a library of general metrics (`runner/runware_eval/metrics_lib/`, listed in
`skills/runware-eval/references/metric-catalog.md`). These four are not in it: they were written
for a product relighting bench, where the brief asks for a specific change (hard key light from the
upper left, a contact shadow) that no general metric measures.

| File | Kind | What it measures |
|---|---|---|
| `lr_lighting_shift.py` | change | how much more light falls on the left half of the product than before |
| `shading_contrast.py` | change | lightness spread inside the product, relative to the input |
| `contact_shadow.py` | change | lightness drop in a band just below the product |
| `backdrop_lightness.py` | preserve | mean lightness change of the backdrop |

To use one, copy it into your bench's `metrics/` folder and refer to its `id` in `bench.yaml`. To
write your own, copy one as a starting point: a `META` dict and a `compute(pair, opt)` function,
following `runner/runware_eval/metric_api.py`. Then run `runware-eval metrics control bench.yaml`:
a `preserve` metric must pass on an unchanged copy of the input, and a `change` metric must fail.

## `serverless-training/`: train on Runware Serverless, then benchmark what you trained

A Serverless app that trains a LoRA in resumable slices and serves it, a local client, the script that
turned a bench run into training pairs, and the recipe that put the trained model back into the bench.
See its `README.md` for the loop and what was measured.
