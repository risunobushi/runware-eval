"""Runware Serverless app: trains an edit LoRA for FLUX.2 [klein] 4B on paired images, in resumable slices.

Why slices: Serverless documents long jobs as many short calls that each save a checkpoint. `train` runs the
official diffusers script (examples/dreambooth/train_dreambooth_lora_flux2_klein_img2img.py, v0.42.1) up to
`max_steps` and returns; calling it again with a higher `max_steps` resumes from the last checkpoint.

Everything lives under /work, a volume: the dataset, the Hugging Face cache (base weights, 16 GB, downloaded
once) and the checkpoints. A volume is local to one machine, so the client downloads each LoRA it wants to keep.

Endpoints: put (upload a file in pieces), setup (unpack the dataset, fetch the training script), train,
status, sample (run the 4-step model with a checkpoint's LoRA on one image), get (download a file in pieces).
"""
import base64
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile

from runware_serverless import endpoint, serve

WORK = "/work"
SCRIPT_URL = ("https://raw.githubusercontent.com/huggingface/diffusers/v0.42.1/examples/dreambooth/"
              "train_dreambooth_lora_flux2_klein_img2img.py")
BASE = "black-forest-labs/FLUX.2-klein-base-4B"   # trained on the base model ...
DISTILLED = "black-forest-labs/FLUX.2-klein-4B"   # ... used on the 4-step distilled one (Apache-2.0, not gated)


def _safe(path):
    full = os.path.realpath(os.path.join(WORK, path))
    if not (full + "/").startswith(WORK + "/"):
        raise ValueError("path must stay inside /work")
    return full


def _tail(path, n=25):
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 6000))
        text = f.read().decode("utf8", "replace").replace("\r", "\n")
    return "\n".join([line for line in text.split("\n") if line.strip()][-n:])


def _checkpoints():
    out = []
    for d in glob.glob(os.path.join(WORK, "out", "checkpoint-*")):
        try:
            out.append(int(d.rsplit("-", 1)[1]))
        except ValueError:
            pass
    return sorted(out)


@serve
class KleinTrainer:
    requirements = ["torch", "torchvision", "diffusers==0.42.1", "transformers", "accelerate", "peft", "datasets",
                    "bitsandbytes", "sentencepiece", "ftfy", "protobuf", "safetensors", "pillow", "huggingface_hub"]

    def load(self) -> None:
        for d in ("in", "out", "hf", "samples"):
            os.makedirs(os.path.join(WORK, d), exist_ok=True)
        os.environ["HF_HOME"] = os.path.join(WORK, "hf")
        self.pipe = None
        self.lora = None

    @endpoint
    def put(self, name: str, data: str, offset: int = 0) -> dict:
        """One piece of a file (base64) into /work/in/<name>. Offset 0 starts the file again."""
        path = _safe(os.path.join("in", os.path.basename(name)))
        raw = base64.b64decode(data)
        with open(path, "wb" if not offset else "r+b") as f:
            f.seek(offset or 0)
            f.write(raw)
        return {"name": os.path.basename(name), "size": os.path.getsize(path)}

    @endpoint
    def setup(self) -> dict:
        """Unpack /work/in/dataset.zip into /work/dataset and fetch the training script."""
        target = os.path.join(WORK, "dataset")
        with zipfile.ZipFile(os.path.join(WORK, "in", "dataset.zip")) as z:
            z.extractall(target)
        script = os.path.join(WORK, "train.py")
        if not os.path.exists(script):
            urllib.request.urlretrieve(SCRIPT_URL, script)
        rows = sum(1 for _ in open(os.path.join(target, "metadata.jsonl"), encoding="utf8"))
        import torch
        return {"pairs": rows, "script_bytes": os.path.getsize(script), "torch": torch.__version__,
                "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                "checkpoints": _checkpoints()}

    @endpoint
    def train(self, max_steps: int, resolution: int = 512, rank: int = 32, learning_rate: float = 1e-4,
              checkpoint_every: int = 250) -> dict:
        """Train until `max_steps` optimizer steps are done in total, resuming from the last checkpoint."""
        resolution, rank = resolution or 512, rank or 32
        learning_rate, checkpoint_every = learning_rate or 1e-4, checkpoint_every or 250
        self.pipe = None  # the sampler's model must not hold GPU memory while training
        import torch
        torch.cuda.empty_cache()
        before = _checkpoints()
        log = os.path.join(WORK, "out", "train.log")
        cmd = [sys.executable, os.path.join(WORK, "train.py"),
               "--pretrained_model_name_or_path", BASE,
               "--dataset_name", os.path.join(WORK, "dataset"),
               "--image_column", "image", "--cond_image_column", "control", "--caption_column", "prompt",
               "--output_dir", os.path.join(WORK, "out"),
               "--resolution", str(resolution), "--train_batch_size", "1", "--gradient_accumulation_steps", "1",
               "--learning_rate", str(learning_rate), "--lr_scheduler", "constant", "--lr_warmup_steps", "0",
               "--rank", str(rank), "--lora_alpha", str(rank), "--mixed_precision", "bf16", "--guidance_scale", "1",
               "--cache_latents", "--max_train_steps", str(max_steps), "--checkpointing_steps", str(checkpoint_every),
               "--resume_from_checkpoint", "latest", "--skip_final_inference", "--seed", "0", "--report_to", "tensorboard"]
        t0 = time.time()
        with open(log, "ab") as f:
            f.write(f"\n=== train to {max_steps} steps at {resolution}px, rank {rank}, lr {learning_rate} ===\n".encode())
            f.flush()
            code = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=WORK,
                                  env={**os.environ, "HF_HOME": os.path.join(WORK, "hf"), "TOKENIZERS_PARALLELISM": "false"}).returncode
        return {"exit_code": code, "seconds": round(time.time() - t0), "checkpoints_before": before,
                "checkpoints": _checkpoints(), "final_lora": os.path.exists(os.path.join(WORK, "out", "pytorch_lora_weights.safetensors")),
                "log": _tail(log)}

    @endpoint
    def status(self) -> dict:
        files = {}
        for root, _, names in os.walk(os.path.join(WORK, "out")):
            for n in names:
                if n.endswith(".safetensors"):
                    p = os.path.join(root, n)
                    files[os.path.relpath(p, WORK)] = os.path.getsize(p)
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader"],
                             capture_output=True, text=True).stdout.strip()
        st = os.statvfs(WORK)
        return {"checkpoints": _checkpoints(), "lora_files": files, "gpu": gpu,
                "disk_free_gb": round(st.f_bavail * st.f_frsize / 1e9, 1), "log": _tail(os.path.join(WORK, "out", "train.log"))}

    @endpoint
    def sample(self, checkpoint: int, image: str, prompt: str, size: int = 1024, steps: int = 4, seed: int = 0,
               guidance: float = 1.0, lora_scale: float = 1.0) -> dict:
        """The 4-step distilled model with one checkpoint's LoRA (0 = no LoRA), on one image (base64). JPEG back.
        `size` is the output's longer side; the input's shape is kept (sides rounded to multiples of 16).
        The LoRA is read from the training output on the volume, or, on a worker whose volume is new, from
        /work/in/lora-<checkpoint>.safetensors (put there with `put`)."""
        import io
        import torch
        from diffusers import Flux2KleinPipeline
        from PIL import Image
        size, steps, seed = size or 1024, steps or 4, seed or 0
        guidance = 1.0 if guidance is None else guidance
        lora_scale = 1.0 if lora_scale is None else lora_scale
        if self.pipe is None:
            self.pipe = Flux2KleinPipeline.from_pretrained(DISTILLED, torch_dtype=torch.bfloat16).to("cuda")
            self.lora = None
        if checkpoint != self.lora:
            if self.lora:
                self.pipe.unload_lora_weights()
            if checkpoint:
                folder, name = os.path.join(WORK, "out", f"checkpoint-{checkpoint}"), "pytorch_lora_weights.safetensors"
                if not os.path.exists(os.path.join(folder, name)):
                    folder, name = os.path.join(WORK, "in"), f"lora-{checkpoint}.safetensors"
                if not os.path.exists(os.path.join(folder, name)):
                    raise FileNotFoundError(f"no LoRA for checkpoint {checkpoint} on this worker: upload it as in/lora-{checkpoint}.safetensors")
                self.pipe.load_lora_weights(folder, weight_name=name)
            self.lora = checkpoint
        src = Image.open(io.BytesIO(base64.b64decode(image))).convert("RGB")
        scale = size / max(src.size)
        w, h = (max(16, int(round(side * scale / 16)) * 16) for side in src.size)
        src = src.resize((w, h), Image.LANCZOS)
        kwargs = {"attention_kwargs": {"scale": lora_scale}} if checkpoint and lora_scale != 1.0 else {}
        t0 = time.time()
        out = self.pipe(prompt=prompt, image=src, height=h, width=w, num_inference_steps=steps,
                        guidance_scale=guidance, generator=torch.Generator("cuda").manual_seed(seed), **kwargs).images[0]
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=92)
        return {"image": base64.b64encode(buf.getvalue()).decode(), "seconds": round(time.time() - t0, 2), "checkpoint": checkpoint,
                "width": w, "height": h}

    @endpoint
    def get(self, path: str, offset: int = 0, length: int = 4000000) -> dict:
        """One piece of a file under /work, base64."""
        full = _safe(path)
        with open(full, "rb") as f:
            f.seek(offset or 0)
            raw = f.read(length or 4000000)
        size = os.path.getsize(full)
        return {"data": base64.b64encode(raw).decode(), "size": size, "eof": (offset or 0) + len(raw) >= size}
