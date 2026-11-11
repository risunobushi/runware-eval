"""Local client for the Serverless trainer app. Uses the Runware CLI login (the key is never printed).

  python client.py upload dataset.zip             put a file on the worker, in pieces
  python client.py call setup                      any endpoint; payload as key=value (numbers parsed)
  python client.py call train max_steps=500 resolution=512
  python client.py call status
  python client.py download out/checkpoint-1500/pytorch_lora_weights.safetensors ../lora/klein4b-relight-1500.safetensors
  python client.py sample 1500 ../inputs/products/product-07-moon-kettle.jpg out.jpg ["prompt"]
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runner"))
from runware_eval import api  # noqa: E402

APP = os.environ.get("TRAINER_APP", "klein-relight-trainer")  # the app id you deployed under
ROOT = "https://api.serverless.runware.ai/v1/apps/" + APP
PROMPT = ("Relight this product photo with one hard key light from the upper left: bright left and top surfaces, deep shadow "
          "on the right side, and a dark, well-defined shadow cast to the right. Keep the product, the white background and "
          "the framing exactly the same.")


def http(method, url, body=None, timeout=120):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method=method, headers={
        "Authorization": f"Bearer {api.api_key()}", "Content-Type": "application/json", "User-Agent": "runware-eval/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf8", "replace")
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, {"detail": text[:500]}


def call(endpoint, payload=None, wait=3600, quiet=False):
    """Async invoke, then poll the task until it is completed or failed. Returns the handler's output."""
    task = str(uuid.uuid4())
    for attempt in range(40):
        code, res = http("POST", f"{ROOT}/invoke-async/{endpoint}", {"taskId": task, "payload": payload or {}})
        if code != 503:
            break
        time.sleep(15)  # no capacity yet: the same task id is sent again, so nothing runs twice
    if code >= 400:
        raise RuntimeError(f"{endpoint}: HTTP {code} {json.dumps(res)[:600]}")
    t0, last = time.time(), None
    while time.time() - t0 < wait:
        status = res.get("status")
        if status != last and not quiet:
            print(f"  [{endpoint}] {status} after {time.time() - t0:.0f}s", flush=True)
            last = status
        if status == "completed":
            out = res.get("output")  # a code app's answer arrives as {"predictions": [<what the handler returned>]}
            if isinstance(out, dict) and list(out) == ["predictions"] and len(out["predictions"]) == 1:
                out = out["predictions"][0]
            return out
        if status == "failed":
            raise RuntimeError(f"{endpoint} failed: {res.get('error')}")
        time.sleep(3 if time.time() - t0 < 60 else 10)
        code, new = http("GET", f"{ROOT}/tasks/{task}")
        if code < 400:
            res = new
        elif code not in (502, 503, 404):
            raise RuntimeError(f"{endpoint}: polling gave HTTP {code} {json.dumps(new)[:300]}")
    raise TimeoutError(f"{endpoint}: not finished after {wait}s (task {task})")


def upload(path, piece=5_000_000):
    name, size, off = os.path.basename(path), os.path.getsize(path), 0
    with open(path, "rb") as f:
        while off < size:
            raw = f.read(piece)
            out = call("put", {"name": name, "data": base64.b64encode(raw).decode(), "offset": off}, quiet=True)
            off += len(raw)
            print(f"  uploaded {off / 1e6:.1f} of {size / 1e6:.1f} MB (on worker: {out['size'] / 1e6:.1f} MB)", flush=True)


def download(remote, local, piece=4_000_000):
    os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    off = 0
    with open(local, "wb") as f:
        while True:
            out = call("get", {"path": remote, "offset": off, "length": piece}, quiet=True)
            raw = base64.b64decode(out["data"])
            f.write(raw)
            off += len(raw)
            print(f"  downloaded {off / 1e6:.1f} of {out['size'] / 1e6:.1f} MB", flush=True)
            if out["eof"] or not raw:
                break
    return off


def sample(checkpoint, image_path, out_path, prompt=PROMPT, size=1024, **extra):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.open(image_path).convert("RGB").resize((size, size), Image.LANCZOS).save(buf, "JPEG", quality=92)
    out = call("sample", {"checkpoint": int(checkpoint), "image": base64.b64encode(buf.getvalue()).decode(), "prompt": prompt,
                          "size": size, **extra}, quiet=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    open(out_path, "wb").write(base64.b64decode(out["image"]))
    return out["seconds"]


def _value(v):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "upload":
        upload(args[0])
    elif cmd == "download":
        download(args[0], args[1])
    elif cmd == "sample":
        print("seconds on the GPU:", sample(args[0], args[1], args[2], *(args[3:4])))
    elif cmd == "call":
        out = call(args[0], {k: _value(v) for k, v in (a.split("=", 1) for a in args[1:])})
        if isinstance(out, dict) and "log" in out:
            log = out.pop("log")
            print(json.dumps(out, indent=1))
            print("--- log ---\n" + log)
        else:
            print(json.dumps(out, indent=1)[:4000])
