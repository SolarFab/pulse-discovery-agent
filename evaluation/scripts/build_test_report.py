#!/usr/bin/env python3
"""Generate the testing & evaluation showcase (docs/showcase/testing-report.html).

Collects REAL results — never hand-edited numbers:
  - pytest:            runs the suite, parses the JUnit XML
  - embedding bench:   docs/embedding-benchmark.md (if present)
  - prompt bench:      docs/prompt-benchmark.md   (if present, later)

Usage:  python scripts/build_test_report.py
Re-run after any benchmark to refresh the showcase.
"""

from __future__ import annotations

import datetime
import html
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "showcase" / "testing-report.html"

STRATEGY = [
    ("L1 · Unit", "Deterministic logic — parsing, taxonomy, facets, embed-text stability. "
     "No network, no DB. Runs on every push (GitHub Actions)."),
    ("L2 · Integration", "The seams — DB-backed tests (local Postgres), RLS user isolation. "
     "Opt-in, planned with the preference feed."),
    ("L3 · End-to-end", "Browser-driven smoke flows (Playwright / webapp-testing). Planned "
     "with the web tasks."),
    ("L4 · Evals", "AI quality is scored, not asserted: embedding benchmark (precision@5 + "
     "golden queries), retrieval eval, prompt benchmark (promptfoo grid). Regression gates "
     "for model/prompt changes."),
]


def run_pytest() -> dict:
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    proc = subprocess.run(
        ["uv", "run", "pytest", "-q", f"--junitxml={xml_path}"],
        cwd=ROOT, capture_output=True, text=True,
    )
    suite = ET.parse(xml_path).getroot().find("testsuite")
    cases = suite.findall("testcase")
    by_file: dict[str, list[dict]] = {}
    for c in cases:
        cls = c.get("classname", "")
        mod = next((p for p in cls.split(".") if p.startswith("test_")), cls or "unknown")
        status = "passed"
        if c.find("failure") is not None or c.find("error") is not None:
            status = "failed"
        elif c.find("skipped") is not None:
            status = "skipped"
        by_file.setdefault(mod, []).append(
            {"name": c.get("name"), "status": status, "time": float(c.get("time", 0))}
        )
    return {
        "total": len(cases),
        "failed": int(suite.get("failures", 0)) + int(suite.get("errors", 0)),
        "skipped": int(suite.get("skipped", 0)),
        "time": float(suite.get("time", 0)),
        "by_file": dict(sorted(by_file.items())),
        "exit": proc.returncode,
    }


def md_section(path: Path) -> str | None:
    """Convert simple benchmark markdown (headings, tables, lists, bold) to HTML."""
    if not path.exists():
        return None
    out, in_table = [], False
    for line in path.read_text().splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>")
                in_table = True
            out.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        line_h = html.escape(line)
        line_h = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line_h)
        if line.startswith("### "):
            out.append(f"<h4>{line_h[4:]}</h4>")
        elif line.startswith("## "):
            out.append(f"<h3>{line_h[3:]}</h3>")
        elif line.startswith("# "):
            continue  # page provides its own title
        elif line.startswith("- "):
            out.append(f"<div class='li'>{line_h[2:]}</div>")
        elif line.strip():
            out.append(f"<p>{line_h}</p>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def build() -> None:
    py = run_pytest()
    findings = md_section(ROOT / "docs" / "FINDINGS.md")
    emb = md_section(ROOT / "docs" / "embedding-benchmark.md")
    qrels = md_section(ROOT / "docs" / "embedding-benchmark-qrels.md")
    retrieval = md_section(ROOT / "docs" / "retrieval-benchmark.md")
    prompt = md_section(ROOT / "docs" / "prompt-benchmark.md")
    stage2 = md_section(ROOT / "docs" / "stage2-benchmark.md")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ok = py["failed"] == 0

    files_html = ""
    for mod, cases in py["by_file"].items():
        passed = sum(1 for c in cases if c["status"] == "passed")
        rows = "".join(
            f"<div class='case {c['status']}'><span>{html.escape(c['name'])}</span>"
            f"<span class='dot'>{'✓' if c['status'] == 'passed' else '✗'}</span></div>"
            for c in cases
        )
        files_html += (
            f"<details><summary><code>{html.escape(mod)}.py</code>"
            f"<span class='count'>{passed}/{len(cases)}</span></summary>{rows}</details>"
        )

    strategy_html = "".join(
        f"<div class='layer'><h3>{html.escape(t)}</h3><p>{html.escape(d)}</p></div>"
        for t, d in STRATEGY
    )

    def section(title: str, body: str | None, placeholder: str) -> str:
        inner = body if body else f"<p class='pending'>{placeholder}</p>"
        return f"<section><h2>{title}</h2>{inner}</section>"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pulse — Testing &amp; Evaluation Report</title>
<style>
  :root {{ color-scheme: light dark; --ok:#16a34a; --bad:#dc2626; --mut:#8b8b93;
          --card:#00000008; --line:#00000018; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --card:#ffffff0d; --line:#ffffff20; }} }}
  body {{ font: 15px/1.55 system-ui, sans-serif; max-width: 880px; margin: 2.5rem auto;
         padding: 0 1.25rem; }}
  h1 {{ font-size: 1.6rem; margin-bottom:.2rem }} h2 {{ font-size:1.15rem; margin-top:2.2rem;
      border-bottom:1px solid var(--line); padding-bottom:.35rem }}
  .sub {{ color: var(--mut); margin-top: 0 }}
  .hero {{ display:flex; gap:1rem; flex-wrap:wrap; margin:1.4rem 0 }}
  .stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:.8rem 1.2rem; min-width:120px }}
  .stat b {{ font-size:1.5rem; display:block }} .stat.ok b {{ color:var(--ok) }}
  .stat.bad b {{ color:var(--bad) }}
  .layer {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding: .2rem 1rem .6rem; margin:.6rem 0 }}
  .layer h3 {{ margin:.6rem 0 .2rem; font-size:1rem }} .layer p {{ margin:.2rem 0; color:var(--mut) }}
  details {{ border:1px solid var(--line); border-radius:8px; margin:.45rem 0;
            padding:.35rem .8rem; background:var(--card) }}
  summary {{ cursor:pointer; display:flex; justify-content:space-between }}
  .count {{ color:var(--ok); font-variant-numeric: tabular-nums }}
  .case {{ display:flex; justify-content:space-between; padding:.18rem .2rem;
          border-top:1px dashed var(--line); font-size:.92em }}
  .case.passed .dot {{ color:var(--ok) }} .case.failed .dot {{ color:var(--bad) }}
  table {{ border-collapse:collapse; margin:.8rem 0; width:100%; overflow-x:auto; display:block }}
  th,td {{ border:1px solid var(--line); padding:.4rem .7rem; text-align:left; font-size:.93em }}
  th {{ background:var(--card) }}
  .pending {{ color:var(--mut); font-style:italic }}
  .li {{ padding-left:1rem }} .li::before {{ content:"– "; color:var(--mut) }}
  code {{ background:var(--card); padding:.1rem .35rem; border-radius:5px }}
  footer {{ color:var(--mut); margin-top:2.5rem; font-size:.85em }}
</style></head><body>
<h1>Pulse — Testing &amp; Evaluation</h1>
<p class="sub">Generated {now} by <code>scripts/build_test_report.py</code> — every number
comes from a real run, nothing is hand-edited.</p>

<div class="hero">
  <div class="stat {'ok' if ok else 'bad'}"><b>{py['total'] - py['failed']}/{py['total']}</b>unit tests passing</div>
  <div class="stat"><b>{py['time']:.1f}s</b>suite runtime</div>
  <div class="stat"><b>{len(py['by_file'])}</b>test modules</div>
  <div class="stat"><b>4</b>test layers</div>
</div>

<section><h2>Strategy — the four layers</h2>{strategy_html}</section>

{section("Key findings (start here)", findings,
         "docs/FINDINGS.md missing.")}

<section><h2>L1 · Unit test results (live)</h2>{files_html}</section>

{section("L4 · Embedding model benchmark", emb,
         "Not yet run — waiting on the OpenRouter key. "
         "scripts/benchmark_embeddings.py fills this section.")}

{section("L4 · Embedding benchmark — hand-labeled qrels", qrels,
         "Awaiting human labels: open docs/showcase/labeling-sheet.html, tick relevant events, "
         "export to eval/golden_set/qrels_v1.jsonl, run scripts/score_qrels.py.")}

{section("L4 · Retrieval ladder — Experiment 2", retrieval,
         "Not yet run: scripts/benchmark_retrieval.py (needs qrels_v1).")}

<section><h2>L4 · Accuracy vs. cost — the model × technique grid</h2>
<iframe src="prompt-scatter.html" title="Tool-call accuracy vs cost per turn"
        style="border:none;width:100%;height:980px;border-radius:8px"></iframe>
<p><a href="prompt-scatter.html">Open the chart full-page</a> (hover for per-cell detail).</p>
</section>

{section("L4 · Stage 2 — end-to-end answer quality (judge)", stage2,
         "Not yet run: scripts/benchmark_stage2.py decides CHAT_MODEL.")}

{section("L4 · Prompt-technique benchmark", prompt,
         "Planned (semantic-search spec, task 4.5): promptfoo grid of prompt variants × chat "
         "models over a golden dialog set — tool-arg accuracy, grounding, dialog-policy "
         "compliance.")}

<footer>Pulse · spec-driven development (OpenSpec) · benchmarks are regression gates:
re-run on every model or prompt change.</footer>
</body></html>""")
    print(f"wrote {OUT} ({'ALL GREEN' if ok else 'FAILURES PRESENT'}, {py['total']} tests)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    build()
