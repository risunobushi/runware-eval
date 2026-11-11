# Train on Serverless, then benchmark what you trained

One loop, run end to end on 2026-11-11, from the brief "I need to train a relighting model on a specific
lighting schema", a lighting reference and twenty generated product photos:

1. **Bench** ten recipes (six closed models as teacher candidates, four open-weights models as student
   candidates, untrained) on five products. The user picked MiniMax H3 as teacher.
2. **Dataset:** the teacher relit all twenty products, five draws each, through the same bench.
   `build_dataset.py` pairs each kept output with its input and leaves out the worst offenders (backdrop
   turned dark, no shadow to the right, product changed, judges said "not the same product"): 85 pairs.
3. **Train** a LoRA for FLUX.2 [klein] 4B (Apache-2.0, not gated, the smallest of the candidates) with
   the official diffusers script, on one L40S on Runware Serverless: `trainer/app.py`, driven by `client.py`.
4. **Benchmark the result:** `klein4b-relight-lora.yaml` is a recipe that calls the app's endpoint, so the
   trained model sits in the bench with the others, on products it never saw.

## What was measured

| | klein 4B untrained | klein 4B trained | Teacher (MiniMax H3) |
|---|---|---|---|
| Checks passed, 10 unseen products | 102 of 145 | 127 of 150 | 131 of 150 |
| Shift of the product | 10.4 px | 0.5 px | 1.1 px |
| Outline overlap | 0.90 | 0.99 | 0.99 |
| Detail kept | 0.09 | 0.35 | 0.40 |
| Cost per output | 0.003 USD | 0.0014 USD | 0.040 USD |

Training: 1500 steps at 512 px, rank 32, 2.2 steps per second, about 11 minutes. Serverless billed 1 h 8 min of
GPU time (1.82 USD) for everything: weight downloads, training, sampling, three benchmark runs, two cold
starts and idle time. The student's cost per output is GPU seconds per call at the L40S rate; cold start
and idle time are billed on top.

What it did not learn: on portraits (nothing like them in the training set) it applies the light but turns
some coloured backdrops white, and it carries the teacher's slightly grey background everywhere.

## The app

`trainer/app.py` is a Serverless code app. Serverless documents long jobs as many short calls that each
save a checkpoint, so `train` runs the training script up to `max_steps` and returns; calling it again
with a higher number resumes. Everything is on one volume (`/work`), which is local to one machine: download
what you want to keep.

```bash
# from trainer/ (on Windows use PowerShell: Git Bash rewrites /work into a Windows path)
runware serverless deploy ./app.py --id klein-relight-trainer --gpu-type l40s --fallback-gpu-type rtx-pro-6000 \
  --volume /work --max-workers 1 --idle-ttl 600 --wait

python client.py upload dataset.zip                      # in pieces of 5 MB: a call carries about 10 MiB
python client.py call setup
python client.py call train max_steps=50 resolution=512  # a short slice first: settings and speed
python client.py call train max_steps=1500 resolution=512
python client.py sample 1500 some-input.jpg out.jpg      # the 4-step model with the checkpoint's LoRA
python client.py download out/checkpoint-1500/pytorch_lora_weights.safetensors my-lora.safetensors
runware serverless apps delete klein-relight-trainer --yes
```

`client.py` uses the runner's login (the Runware CLI's), so run it with the runner's Python:
`uv run --project ../../runner python client.py ...`.

## Things that were not obvious

- A code app's answer arrives as `{"predictions": [<what the handler returned>]}`.
- There is no CPU instance: `--gpu-type` is required, and a worker is only provisioned on the first call.
- A worker reaches GitHub and Hugging Face with no setup. Models that need a Hugging Face login need a token
  as a Serverless secret; FLUX.2 klein 4B does not.
- A cold start with the weights already on the volume took about 6 minutes.
- The limits a bench freezes hold for the inputs they were set on: the dataset was not filtered with them.
