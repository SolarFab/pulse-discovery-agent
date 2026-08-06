#!/usr/bin/env python3
"""Scatter: tool-call accuracy vs measured cost/turn for every prompt-variant x model cell.

Encoding: COLOR = model (categorical slots 1-8 + neutral gray for the cost anchor),
SHAPE = prompting technique (4 shapes). Reads the newest eval/results/prompts-*.json
(needs usd_per_turn) and writes docs/showcase/prompt-scatter.html — self-contained,
light+dark, hover tooltips, log-x, Pareto frontier, table view.
Palette: dataviz default slots; identity is never color-alone (legend+tooltip+table).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "showcase" / "prompt-scatter.html"

VARIANT_ORDER = ["zero-shot", "prod-v1", "few-shot", "clarify-first"]
SHAPES = {"zero-shot": "circle", "prod-v1": "square",
          "few-shot": "diamond", "clarify-first": "triangle"}

# Fixed slot order (dataviz palette); gray = cost anchor, not a candidate.
MODEL_SLOTS = [
    ("anthropic/claude-haiku-4.5", "#2a78d6", "#3987e5"),
    ("openai/gpt-4o-mini", "#008300", "#008300"),
    ("google/gemini-2.5-flash", "#e87ba4", "#d55181"),
    ("deepseek/deepseek-v4-flash", "#eda100", "#c98500"),
    ("deepseek/deepseek-v4-pro", "#1baf7a", "#199e70"),
    ("minimax/minimax-m2.7", "#eb6834", "#d95926"),
    ("z-ai/glm-5.2", "#4a3aa7", "#9085e9"),
    ("google/gemma-4-31b-it", "#e34948", "#e66767"),
    ("openai/gpt-4.1-nano", "#6b6b6b", "#9a9a94"),   # anchor -> neutral
]

W, H = 880, 540
ML, MR, MT, MB = 70, 30, 20, 92


def slug(model: str) -> str:
    return model.split("/")[-1].replace(".", "-")


def short(model: str) -> str:
    return model.split("/")[-1].replace("-instruct", "").replace("-it", "")


def latest_results() -> dict:
    files = sorted((ROOT / "eval" / "results").glob("prompts-*.json"))
    for f in reversed(files):
        data = json.loads(f.read_text())
        cells = list(data["results"].values())
        if cells and "usd_per_turn" in cells[0]:
            return data
    raise SystemExit("no prompts-*.json with cost data found — run benchmark_prompts.py first")


def shape_path(shape: str, x: float, y: float, r: float = 6) -> str:
    if shape == "circle":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>'
    if shape == "square":
        return f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" rx="1.5"/>'
    if shape == "diamond":
        return (f'<path d="M{x:.1f} {y - r - 1:.1f} L{x + r + 1:.1f} {y:.1f} '
                f'L{x:.1f} {y + r + 1:.1f} L{x - r - 1:.1f} {y:.1f} Z"/>')
    return (f'<path d="M{x:.1f} {y - r - 1:.1f} L{x + r + 1:.1f} {y + r:.1f} '
            f'L{x - r - 1:.1f} {y + r:.1f} Z"/>')


def main() -> None:
    data = latest_results()
    cells = [r for r in data["results"].values() if r.get("usd_per_turn", 0) > 0]
    known = {m for m, _, _ in MODEL_SLOTS}
    for c in cells:
        if c["model"] not in known:
            raise SystemExit(f"model {c['model']} has no palette slot — extend MODEL_SLOTS")
    models_present = [m for m, _, _ in MODEL_SLOTS if any(c["model"] == m for c in cells)]

    xs = [c["usd_per_turn"] for c in cells]
    lo = 10 ** math.floor(math.log10(min(xs)) - 0.15)
    hi = 10 ** math.ceil(math.log10(max(xs)) + 0.05)

    def X(v: float) -> float:
        return ML + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (W - ML - MR)

    def Y(score: float) -> float:
        return MT + (1 - score) * (H - MT - MB)

    pareto = sorted(
        (c for c in cells
         if not any(o["usd_per_turn"] <= c["usd_per_turn"] and o["score"] > c["score"]
                    or o["usd_per_turn"] < c["usd_per_turn"] and o["score"] >= c["score"]
                    for o in cells)),
        key=lambda c: c["usd_per_turn"])
    pareto_keys = {(c["variant"], c["model"]) for c in pareto}

    grid, ticks = [], []
    for e in range(int(math.floor(math.log10(lo))), int(math.ceil(math.log10(hi))) + 1):
        for m in (1, 3):
            v = m * 10 ** e
            if lo <= v <= hi:
                x = X(v)
                grid.append(f'<line x1="{x:.1f}" y1="{MT}" x2="{x:.1f}" y2="{H - MB}" class="grid"/>')
                lbl = ("$" + f"{v:.5f}".rstrip("0")) if v < 0.01 else f"${v:g}"
                ticks.append(f'<text x="{x:.1f}" y="{H - MB + 18}" class="tick" text-anchor="middle">{lbl}</text>')
    for s in (0.25, 0.5, 0.75, 1.0):
        y = Y(s)
        grid.append(f'<line x1="{ML}" y1="{y:.1f}" x2="{W - MR}" y2="{y:.1f}" class="grid"/>')
        ticks.append(f'<text x="{ML - 8}" y="{y + 4:.1f}" class="tick" text-anchor="end">{s:.0%}</text>')

    pline = " ".join(f"{X(c['usd_per_turn']):.1f},{Y(c['score']):.1f}" for c in pareto)
    marks, labels = [], []
    for c in cells:
        x, y = X(c["usd_per_turn"]), Y(c["score"])
        v, m = c["variant"], c["model"]
        tip = (f"{v} × {short(m)} — {c['passed']}/{c['of']} ({c['score']:.0%}), "
               f"${c['usd_per_turn']:.5f}/turn, {c['mean_ms']}ms")
        marks.append(f'<g class="pt m-{slug(m)}" data-tip="{tip}">{shape_path(SHAPES[v], x, y)}</g>')
        if (v, m) in pareto_keys:
            labels.append(f'<text x="{x + 10:.1f}" y="{y - 8:.1f}" class="ptlabel">{short(m)}</text>')

    shape_legend = "".join(
        f'<span class="lg shape"><svg width="16" height="16" viewBox="-8 -8 16 16">'
        f"{shape_path(SHAPES[v], 0, 0, 5)}</svg>{v}</span>"
        for v in VARIANT_ORDER)
    model_legend = "".join(
        f'<span class="lg m-{slug(m)}"><svg width="14" height="14" viewBox="-7 -7 14 14">'
        f'<circle r="5"/></svg>{short(m)}</span>'
        for m in models_present)

    rows = "".join(
        f"<tr><td>{c['variant']}</td><td>{short(c['model'])}</td>"
        f"<td>{c['passed']}/{c['of']} ({c['score']:.0%})</td>"
        f"<td>${c['usd_per_turn']:.5f}</td><td>{c['mean_ms']}</td></tr>"
        for c in sorted(cells, key=lambda c: (-c["score"], c["usd_per_turn"])))

    css_light = "\n".join(f" .viz-root .m-{slug(m)} {{ --c: {light} }}" for m, light, _ in MODEL_SLOTS)
    css_dark = "\n".join(f"    .viz-root .m-{slug(m)} {{ --c: {dark} }}" for m, _, dark in MODEL_SLOTS)

    OUT.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pulse — prompt benchmark: accuracy vs cost</title>
<style>
 .viz-root {{ color-scheme: light; --surface-1:#ffffff; --text-primary:#111;
   --text-secondary:#555; --grid:#00000014; font:14px/1.5 system-ui,sans-serif;
   max-width:940px; margin:2rem auto; padding:0 1rem; color:var(--text-primary);
   background:var(--surface-1) }}
{css_light}
 @media (prefers-color-scheme: dark) {{
   :root:where(:not([data-theme="light"])) .viz-root {{ color-scheme:dark;
     --surface-1:#1a1a19; --text-primary:#fff; --text-secondary:#c3c2b7; --grid:#ffffff1e }}
{css_dark}
 }}
 :root[data-theme="dark"] .viz-root {{ color-scheme:dark; --surface-1:#1a1a19;
   --text-primary:#fff; --text-secondary:#c3c2b7; --grid:#ffffff1e }}
 body {{ margin:0; background:var(--surface-1,#fff) }}
 h1 {{ font-size:1.25rem; margin-bottom:.2rem }}
 .sub {{ color:var(--text-secondary); margin-top:0 }}
 svg.chart {{ width:100%; height:auto; display:block }}
 .grid {{ stroke:var(--grid); stroke-width:1 }}
 .tick, .axis {{ fill:var(--text-secondary); font-size:12px }}
 .pt * {{ fill:var(--c); stroke:var(--surface-1); stroke-width:2 }}
 .pt {{ cursor:pointer }}
 .ptlabel {{ fill:var(--text-secondary); font-size:11px }}
 .pareto {{ fill:none; stroke:var(--text-secondary); stroke-width:1; stroke-dasharray:3 4; opacity:.6 }}
 .legendrow {{ margin:.3rem 0 }}
 .legendrow b {{ color:var(--text-secondary); font-weight:600; font-size:.85em; margin-right:.6rem }}
 .lg {{ display:inline-flex; align-items:center; gap:.3rem; margin-right:.9rem;
       color:var(--text-secondary); font-size:.88em }}
 .lg svg * {{ fill:var(--c) }}
 .lg.shape svg * {{ fill:var(--text-secondary) }}
 #tip {{ position:fixed; pointer-events:none; background:var(--text-primary);
   color:var(--surface-1); padding:.35rem .6rem; border-radius:6px; font-size:.85em;
   opacity:0; transition:opacity .12s; max-width:360px; z-index:9 }}
 table {{ border-collapse:collapse; margin-top:1.5rem; width:100% }}
 th,td {{ border:1px solid var(--grid); padding:.35rem .6rem; font-size:.9em; text-align:left }}
 th {{ color:var(--text-secondary) }}
</style></head><body><div class="viz-root">
<h1>Tool-call accuracy vs. measured cost per turn</h1>
<p class="sub">Experiment 3 stage 1 · {len(cells)} technique × model cells · golden set v1 (13 chat
queries, deterministic asserts, temp 0) · cost = OpenRouter usage accounting · dashed = Pareto
frontier · up &amp; left is better · gray = cost anchor</p>
<div class="legendrow"><b>SHAPE = technique</b>{shape_legend}</div>
<div class="legendrow"><b>COLOR = model</b>{model_legend}</div>
<svg class="chart" viewBox="0 0 {W} {H}" role="img"
     aria-label="Scatter plot of tool-call accuracy against cost per turn">
  {''.join(grid)}
  <polyline class="pareto" points="{pline}"/>
  {''.join(marks)}
  {''.join(labels)}
  {''.join(ticks)}
  <text x="{(ML + W - MR) / 2}" y="{H - MB + 44}" class="axis" text-anchor="middle">cost per turn (USD, log scale)</text>
  <text x="18" y="{(MT + H - MB) / 2}" class="axis" text-anchor="middle"
        transform="rotate(-90 18 {(MT + H - MB) / 2})">tool-call accuracy</text>
</svg>
<div id="tip"></div>
<table><tr><th>technique</th><th>model</th><th>accuracy</th><th>$/turn</th><th>ms/turn</th></tr>{rows}</table>
<p class="sub">Run: {data.get('experiment')} · models: {', '.join(short(m) for m in data.get('models', []))}</p>
<script>
const tip = document.getElementById('tip');
document.querySelectorAll('.pt').forEach(p => {{
  p.addEventListener('mousemove', e => {{
    tip.textContent = p.dataset.tip;
    tip.style.left = (e.clientX + 14) + 'px';
    tip.style.top = (e.clientY - 10) + 'px';
    tip.style.opacity = 1;
  }});
  p.addEventListener('mouseleave', () => tip.style.opacity = 0);
}});
</script>
</div></body></html>""")
    print(f"wrote {OUT} ({len(cells)} points, {len(pareto)} on the frontier, "
          f"{len(models_present)} models)")


if __name__ == "__main__":
    main()
