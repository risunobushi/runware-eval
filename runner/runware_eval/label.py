"""A blind labeling page: mark outputs good or bad, and pick the better of random pairs.

Model names are hidden and the order is shuffled, so the labels reflect the images, not the brands.
The page downloads `labels.json`; `runware-eval calibrate` reads it.
"""
import itertools
import json
import os
import random

from PIL import Image

from ._assets import CSS
from .report import uri
from .bench import stem

PAGE_CSS = """
.task{display:grid;gap:14px}.row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}
.row figure{margin:0;display:grid;gap:4px}.row img{width:100%;height:auto;max-height:58vh;object-fit:contain;background:var(--card);border-radius:8px;border:1px solid var(--grid)}
.btns{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.btns button{font:inherit;font-size:14px;padding:8px 14px;
border-radius:8px;border:1px solid var(--grid);background:var(--card);color:var(--ink);cursor:pointer}
.btns button.on{border-color:var(--accent);box-shadow:inset 0 -2px 0 var(--accent)}
.progress{font-size:13px;color:var(--ink2)}.kbd{font-family:ui-monospace,monospace;font-size:12px;
border:1px solid var(--grid);border-radius:4px;padding:0 5px}
.tabs{display:flex;gap:6px}.tabs button{font:inherit;padding:6px 12px;border-radius:7px;border:1px solid var(--grid);
background:var(--card);color:var(--ink);cursor:pointer}.tabs button[aria-pressed=true]{border-color:var(--accent);
box-shadow:inset 0 -2px 0 var(--accent)}
"""

JS = """
const D = JSON.parse(document.getElementById('data').textContent);
const S = {labels: {}, pairs: {}, i: 0, j: 0, tab: 'label'};
const $ = id => document.getElementById(id);
function render(){
  $('t-label').hidden = S.tab !== 'label'; $('t-pair').hidden = S.tab !== 'pair';
  document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-pressed', b.dataset.tab === S.tab));
  const it = D.items[S.i];
  $('l-orig').src = D.originals[it.input]; $('l-out').src = D.img[it.file];
  $('l-prog').textContent = `Output ${S.i + 1} of ${D.items.length} · labeled ${Object.keys(S.labels).length}`;
  document.querySelectorAll('[data-lab]').forEach(b => b.classList.toggle('on', S.labels[it.file] === b.dataset.lab));
  if (D.pairs.length){
    const p = D.pairs[S.j];
    $('p-orig').src = D.originals[p.input]; $('p-a').src = D.img[p.a]; $('p-b').src = D.img[p.b];
    $('p-prog').textContent = `Pair ${S.j + 1} of ${D.pairs.length} · answered ${Object.keys(S.pairs).length}`;
    document.querySelectorAll('[data-win]').forEach(b => b.classList.toggle('on', S.pairs[S.j] === b.dataset.win));
  }
}
function lab(v){ S.labels[D.items[S.i].file] = v; if (S.i < D.items.length - 1) S.i++; render(); }
function win(v){ S.pairs[S.j] = v; if (S.j < D.pairs.length - 1) S.j++; render(); }
document.querySelectorAll('[data-lab]').forEach(b => b.onclick = () => lab(b.dataset.lab));
document.querySelectorAll('[data-win]').forEach(b => b.onclick = () => win(b.dataset.win));
document.querySelectorAll('[data-nav]').forEach(b => b.onclick = () => {
  const d = +b.dataset.nav;
  if (S.tab === 'label') S.i = Math.max(0, Math.min(D.items.length - 1, S.i + d));
  else S.j = Math.max(0, Math.min(D.pairs.length - 1, S.j + d)); render(); });
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => { S.tab = b.dataset.tab; render(); });
document.addEventListener('keydown', ev => {
  if (S.tab === 'label') { if (ev.key === 'g') lab('good'); if (ev.key === 'b') lab('bad'); }
  else { if (ev.key === 'ArrowLeft') win('a'); if (ev.key === 'ArrowRight') win('b'); if (ev.key === 'ArrowDown') win('tie'); }
});
$('save').onclick = () => {
  const out = {bench: D.bench, run: D.run, labels: S.labels,
    pairs: Object.entries(S.pairs).map(([k, w]) => ({a: D.pairs[k].a, b: D.pairs[k].b, winner: w}))};
  const blob = new Blob([JSON.stringify(out, null, 1)], {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'labels.json'; a.click();
};
render();
"""


def build(b, out_dir, pairs_per_recipe=4, seed=7, px=640):
    data = json.load(open(os.path.join(out_dir, "scores.json"), encoding="utf8"))
    scored = data["scored"]
    rng = random.Random(seed)
    inputs = {stem(i["path"]): i for i in b["inputs"]}
    originals = {k: uri(Image.open(os.path.join(b["_dir"], inputs[k]["path"])).convert("RGB"), px, 82)
                 for k in {s["input"] for s in scored}}
    img = {}
    for s in scored:
        path = os.path.join(out_dir, s.get("view") or s["file"])
        img[s["file"]] = uri(Image.open(path).convert("RGB"), px, 82)
    items = [{"file": s["file"], "input": s["input"], "img": img[s["file"]]} for s in scored]
    rng.shuffle(items)
    # pairs: same input, different recipes; about `pairs_per_recipe` appearances per recipe
    pairs = []
    by_input = {}
    for s in scored:
        by_input.setdefault(s["input"], []).append(s)
    pool = [(x, y) for ss in by_input.values() for x, y in itertools.combinations(ss, 2) if x["recipe"] != y["recipe"]]
    rng.shuffle(pool)
    want = pairs_per_recipe * len({s["recipe"] for s in scored}) // 2 or 1
    for x, y in pool[:want]:
        a, c = (x, y) if rng.random() < 0.5 else (y, x)
        pairs.append({"a": a["file"], "b": c["file"], "input": a["input"]})
    payload = {"bench": b.get("title") or b["goal"][:80], "run": os.path.basename(out_dir.rstrip("/\\")),
               "items": [{k: v for k, v in it.items() if k != "img"} for it in items],
               "img": img, "originals": originals, "pairs": pairs}
    html = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>Label outputs</title><style>{CSS}{PAGE_CSS}</style>"
            f"</head><body><div class='wrap'><header style='display:grid;gap:10px'><h1>Label the outputs</h1>"
            f"<p class='ink2'>Blind: model names are hidden and the order is shuffled. Judge each output against "
            f"your own idea of good for this goal. You don't need to finish; label what you can, then save.</p>"
            f"<div class='tabs'><button data-tab='label'>1 · Good or bad</button>"
            f"<button data-tab='pair'>2 · Which is better ({len(pairs)} pairs)</button>"
            f"<button id='save' style='margin-left:auto'>Download labels.json</button></div></header>"
            f"<section id='t-label' class='task'><div class='row'><figure><img id='l-orig' alt='Original'>"
            f"<figcaption>original</figcaption></figure><figure><img id='l-out' alt='Output'>"
            f"<figcaption>output</figcaption></figure></div><div class='btns'>"
            f"<button data-lab='good'>Good <span class='kbd'>g</span></button>"
            f"<button data-lab='bad'>Bad <span class='kbd'>b</span></button>"
            f"<button data-nav='-1'>← back</button><button data-nav='1'>skip →</button>"
            f"<span class='progress' id='l-prog'></span></div></section>"
            f"<section id='t-pair' class='task' hidden><figure style='margin:0;max-width:300px'><img id='p-orig' "
            f"alt='Original' style='width:100%;border-radius:8px'><figcaption>original</figcaption></figure>"
            f"<div class='row'><figure><img id='p-a' alt='Option A'><figcaption>A</figcaption></figure>"
            f"<figure><img id='p-b' alt='Option B'><figcaption>B</figcaption></figure></div><div class='btns'>"
            f"<button data-win='a'>A is better <span class='kbd'>←</span></button>"
            f"<button data-win='b'>B is better <span class='kbd'>→</span></button>"
            f"<button data-win='tie'>About the same <span class='kbd'>↓</span></button>"
            f"<button data-nav='-1'>← back</button><button data-nav='1'>skip →</button>"
            f"<span class='progress' id='p-prog'></span></div></section>"
            f"<script type='application/json' id='data'>{json.dumps(payload)}</script><script>{JS}</script>"
            f"</div></body></html>")
    path = os.path.join(out_dir, "label.html")
    open(path, "w", encoding="utf8").write(html)
    return path, len(items), len(pairs)
