# bench.yaml format

One file describes a bench completely. The runner reads it; an agent writes it. Adding a model
later means adding one recipe and re-running. Results are cached by a hash of
(input, recipe, seed), so a re-run only pays for new combinations.

## Fields

| Field | Meaning |
|---|---|
| `goal` | The user's goal in their own words. |
| `inputs` | Files or URLs. Each may carry its own `region` masks and expected `text`. |
| `regions` | Named masks: a file path, or `auto:<model AIR>` to generate one on Runware (e.g. BiRefNet). |
| `evaluate` | The dimensions the user chose. Per dimension: `mode` (`gate` or `rank`) and `metrics` (ids from `metrics.md` with thresholds). |
| `calibration` | For judge or aesthetic metrics: how many outputs the user labels. |
| `budget` | `max_usd` for one full run. The runner refuses to start above it. |
| `seeds` | Seeds per recipe, to measure consistency. |
| `recipes` | Each: `id`, `model` (AIR), `params` (exact schema field names), `mask` (region and polarity), `notes` (every convention translated). |

## Example

```yaml
goal: "Add a soft contact shadow. The product and the backdrop colour must not change."
inputs:
  - { path: inputs/sneaker_side.png, regions: { product: auto:runware:112@5 } }
  - { path: inputs/boot_front.png,   regions: { product: masks/boot_front.png } }

evaluate:
  pixel_shift:
    mode: gate
    metrics:
      - { id: size_aspect }
      - { id: phase_correlation, max_px: 1 }
  deviation:
    mode: gate
    metrics:
      - { id: deltaE2000_region, region: product, mean_max: 1.0, p95_max: 2.0 }
      - { id: ssim_region, region: product, min: 0.98 }
      - { id: deltaE2000_region, region: not(product), mean_max: 1.5 }
  prompt_adherence:
    mode: gate
    metrics:
      - { id: task_specific, name: contact_shadow, below: product, dL_min: 8, dL_max: 30 }
  aesthetics:
    mode: rank
    metrics:
      - { id: vlm_rubric, judges: [3 vision models from different providers] }
      - { id: pairwise_human }

calibration: { label_count: 8 }
budget: { max_usd: 5.00 }
seeds: [1, 2]

recipes:
  - id: precise-edit-high
    model: "ideogram:4.5@precise-edit"
    params: { quality: high, positivePrompt: "<shadow-only prompt>" }
    mask: { region: product, polarity: edit_is_white, use: not(product) }
    notes: "maskImage: white = edit, black = preserve. Pass the inverted product mask."
  - id: precise-edit-very-low
    model: "ideogram:4.5@precise-edit"
    params: { quality: very_low, positivePrompt: "<shadow-only prompt>" }
    mask: { region: product, polarity: edit_is_white, use: not(product) }
    notes: "Cheapest tier of the same model. Tests whether pixel restoration holds at low quality."
  - id: nano-banana-2-1
    model: "google:nano-banana@2.1"
    params: { positivePrompt: "<shadow-only prompt>" }
    notes: "No mask input. Preservation relies on the prompt."
```

The model IDs above are examples. Always confirm `live` status, `x-modes` and field names through
`model_schema` before writing a recipe.
