"""Metric catalogue: the curated library plus a bench's own and shared metric folders.

Same principle as recipes: one file per metric, fingerprinted. Resolution order (first wins):
the bench's `metricDirs` in the order listed (default `metrics/` next to bench.yaml), then the
library shipped with the runner. A bench metric with a library id overrides it.

Metric files are code. They are only loaded from local folders, never from a URL; review a shared
metric before adding it, and use its fingerprint to pin the version you reviewed.
"""
import glob
import hashlib
import importlib.util
import os

LIBRARY = os.path.join(os.path.dirname(__file__), "metrics_lib")
REQUIRED_META = ("id", "family", "trust", "kind", "description")


def _load(path, source):
    code = open(path, "rb").read()
    fp = hashlib.sha256(code).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(f"rwe_metric_{fp}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    meta = getattr(mod, "META", None)
    fn = getattr(mod, "compute", None)
    if not isinstance(meta, dict) or not callable(fn):
        raise ValueError(f"{path}: a metric file needs a META dict and a compute(pair, opt) function")
    missing = [k for k in REQUIRED_META if k not in meta]
    if missing:
        raise ValueError(f"{path}: META is missing {', '.join(missing)}")
    return {"id": meta["id"], "meta": meta, "compute": fn, "fp": fp, "source": source, "path": path}


def dirs(b=None):
    out = []
    if b is not None:
        for d in b.get("metricDirs") or b.get("metric_dirs") or ["metrics"]:
            out.append((os.path.join(b["_dir"], d), "bench" if d == "metrics" else f"shared:{d}"))
    out.append((LIBRARY, "library"))
    return out


def load(b=None):
    """All metrics visible to a bench, by id (first folder wins)."""
    reg = {}
    for d, source in dirs(b):
        for path in sorted(glob.glob(os.path.join(d, "*.py"))):
            if os.path.basename(path).startswith("_"):
                continue
            m = _load(path, source)
            if m["id"] in reg:
                reg[m["id"]].setdefault("overrides", []).append(m["source"])
                continue
            reg[m["id"]] = m
    return reg


def markdown(reg):
    """The registry as a Markdown table, generated from the metric files themselves."""
    rows = ["| id | kind | family | trust | needs | unit / direction | source | fingerprint |",
            "|---|---|---|---|---|---|---|---|"]
    for mid, m in sorted(reg.items(), key=lambda x: (x[1]["meta"]["family"], x[0])):
        meta = m["meta"]
        rows.append(f"| `{mid}` | {meta['kind']} | {meta['family']} | {meta['trust']} | "
                    f"{', '.join(meta.get('needs', [])) or '—'} | {meta.get('unit', '')} "
                    f"{meta.get('direction', '')} | {m['source']} | `{m['fp'][:8]}` |")
    rows.append("")
    rows += [f"- **`{mid}`**: {m['meta']['description']}" for mid, m in sorted(reg.items())]
    return "\n".join(rows)
