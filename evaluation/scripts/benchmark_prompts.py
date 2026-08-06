#!/usr/bin/env python3
"""Experiment 3 (stage 1) — prompt-technique benchmark on TOOL-CALL accuracy.

Grid: prompt variants (eval/prompts/*.txt) x chat models, over the golden set's chat
queries. Stage 1 asserts the FIRST model action deterministically — right tool, right
args, dates resolved, or correctly NO tool (chitchat / clarify) — no tool execution,
no judge. (Stage 2, grounded end-to-end answers + LLM rubric, follows once a variant
wins here.)

Writes eval/results/prompts-<ts>.json and docs/prompt-benchmark.md.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
BERLIN = ZoneInfo("Europe/Berlin")
# Restricted to the account's OpenRouter allowlist.
MODELS = [
    "anthropic/claude-haiku-4.5",       # shipped default
    "openai/gpt-4o-mini",               # cheap closed baseline
    "google/gemini-2.5-flash",          # Gemini fast tier
    "deepseek/deepseek-v4-flash",       # open: DeepSeek cheap tier
    "deepseek/deepseek-v4-pro",         # open: DeepSeek strong tier
    "minimax/minimax-m2.7",             # open: MiniMax
    "z-ai/glm-5.2",                     # open: Zhipu GLM
    "google/gemma-4-31b-it",            # open: Gemma
    "openai/gpt-4.1-nano",              # ultra-cheap closed anchor
]
VARIANTS = ["zero-shot", "prod-v1", "few-shot", "clarify-first"]

# Tool schema: mirror of web/src/lib/ai/tools.ts (OpenAI function format).
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_events",
            "description": "Search Berlin events. Filters are strict; `query` only ranks "
                           "within them. Returns compact rows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string", "enum": [
                        "culture", "family", "food", "markets", "meetups", "music",
                        "nightlife", "outdoors", "workshops"]},
                    "subcategory": {"type": "string"},
                    "date_from": {"type": "string"}, "date_to": {"type": "string"},
                    "neighborhood": {"type": "string"}, "venue": {"type": "string"},
                    "family_friendly": {"type": "boolean"},
                    "outdoor": {"type": "boolean"}, "free_entry": {"type": "boolean"},
                    "max_price_cents": {"type": "integer"},
                    "lat": {"type": "number"}, "lng": {"type": "number"},
                    "radius_km": {"type": "number"}, "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_event_details",
            "description": "Full record for one event by id.",
            "parameters": {"type": "object",
                           "properties": {"event_id": {"type": "string"}},
                           "required": ["event_id"]},
        },
    },
]


def now_berlin() -> datetime:
    return datetime.now(UTC).astimezone(BERLIN)


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(BERLIN)
    except ValueError:
        return None


def next_weekday(base: datetime, weekday: int) -> datetime:
    d = base + timedelta(days=(weekday - base.weekday()) % 7)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


# ── Assertions: qid -> checker(first_action) -> list of failed check names ────
# first_action = {"tool": name|None, "args": dict, "text": str}

def _search(a):  # helper guards
    return a["tool"] == "search_events"


def check_q07(a):  # etwas Chilliges nach der Arbeit
    fails = []
    if not _search(a):
        return ["called search_events"]
    if not a["args"].get("query"):
        fails.append("semantic query set (vibe needs ranking)")
    return fails


def check_q11(a):  # free open air cinema
    fails = []
    if not _search(a):
        return ["called search_events"]
    if a["args"].get("free_entry") is not True:
        fails.append("free_entry=true")
    if a["args"].get("outdoor") is not True and "kino" not in str(a["args"].get("query", "")).lower() \
            and "open air" not in str(a["args"].get("query", "")).lower() \
            and "cinema" not in str(a["args"].get("query", "")).lower():
        fails.append("outdoor=true or open-air query")
    return fails


def check_q14(a):  # Schillerkiez
    if not _search(a):
        return ["called search_events"]
    args = a["args"]
    geo = args.get("lat") is not None and args.get("lng") is not None
    hood = "neuk" in str(args.get("neighborhood", "")).lower()
    q = "schillerkiez" in str(args.get("query", "")).lower()
    return [] if (geo or hood or q) else ["geo params, Neukölln or Schillerkiez query"]


def check_q15(a):  # SchwuZ this week
    if not _search(a):
        return ["called search_events"]
    return [] if "schwuz" in str(a["args"].get("venue", "")).lower() else ["venue=SchwuZ"]


def check_q16(a):  # kostenlos am Sonntag
    fails = []
    if not _search(a):
        return ["called search_events"]
    if a["args"].get("free_entry") is not True:
        fails.append("free_entry=true")
    sunday = next_weekday(now_berlin(), 6)
    df, dt_ = parse_dt(a["args"].get("date_from")), parse_dt(a["args"].get("date_to"))
    if not (df and dt_ and df <= sunday + timedelta(hours=23) and dt_ >= sunday):
        fails.append("date window covers Sunday")
    return fails


def check_q17(a):  # broad "Was geht heute Abend?" — answer-first => search now
    return [] if _search(a) else ["searched first (answer-first policy)"]


def check_q18(a):  # "Plan uns was Schönes" — ambiguous => clarify, no tool yet
    fails = []
    if a["tool"] is not None:
        fails.append("no tool before clarifying")
    if "?" not in a["text"]:
        fails.append("asked a clarifying question")
    return fails


def check_q19(a):  # Opernball in Marzahn — must still try a search
    return [] if _search(a) else ["attempted a search"]


def check_q21(a):  # profile prefers electronic; user asks jazz — explicit ask wins
    if not _search(a):
        return ["called search_events"]
    blob = json.dumps(a["args"]).lower()
    if "electronic" in blob or "techno" in blob:
        return ["profile must not redirect (electronic leaked into args)"]
    return [] if ("jazz" in blob) else ["jazz in query/subcategory"]


def check_q22(a):  # chitchat
    return [] if a["tool"] is None else ["no tool call for chitchat"]


def check_q23(a):  # live music tomorrow evening
    fails = []
    if not _search(a):
        return ["called search_events"]
    tomorrow = (now_berlin() + timedelta(days=1)).date()
    df = parse_dt(a["args"].get("date_from"))
    if not (df and df.date() == tomorrow and df.hour >= 15):
        fails.append("date_from = tomorrow evening")
    blob = json.dumps(a["args"]).lower()
    if not ("live" in blob or "konzert" in blob or "concert" in blob):
        fails.append("live-music intent in query/subcategory")
    return fails


def check_q24(a):  # rap
    if not _search(a):
        return ["called search_events"]
    blob = json.dumps(a["args"]).lower()
    return [] if ("rap" in blob or "hip" in blob) else ["rap/hip-hop in args"]


def check_q25(a):  # kids weekend, preferably outside (soft!)
    fails = []
    if not _search(a):
        return ["called search_events"]
    if a["args"].get("family_friendly") is not True:
        fails.append("family_friendly=true")
    sat = next_weekday(now_berlin(), 5)
    df, dt_ = parse_dt(a["args"].get("date_from")), parse_dt(a["args"].get("date_to"))
    if not (df and dt_ and df <= sat + timedelta(days=1, hours=23) and dt_ >= sat):
        fails.append("date window covers the weekend")
    return fails


CHECKS = {"q07": check_q07, "q11": check_q11, "q14": check_q14, "q15": check_q15,
          "q16": check_q16, "q17": check_q17, "q18": check_q18, "q19": check_q19,
          "q21": check_q21, "q22": check_q22, "q23": check_q23, "q24": check_q24,
          "q25": check_q25}


def chat_call(model: str, system: str, user: str) -> tuple[dict, int, float, float]:
    t0 = time.time()
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={"model": model, "temperature": 0, "tools": TOOLS,
              "usage": {"include": True},  # measured USD cost per call, not price-sheet math
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=90,
    )
    resp.raise_for_status()
    body = resp.json()
    ms = (time.time() - t0) * 1000
    usage = body.get("usage") or {}
    tokens = usage.get("total_tokens", 0)
    usd = float(usage.get("cost") or 0.0)
    msg = body["choices"][0]["message"]
    tc = (msg.get("tool_calls") or [None])[0]
    action = {
        "tool": tc["function"]["name"] if tc else None,
        "args": json.loads(tc["function"]["arguments"]) if tc else {},
        "text": msg.get("content") or "",
    }
    return action, tokens, ms, usd


def model_available(model: str) -> bool:
    """One cheap probe; a wrong model id must skip the model, not zero its scores."""
    try:
        chat_call(model, "Reply with OK.", "ping")
        return True
    except Exception as exc:
        detail = ""
        if hasattr(exc, "response") and exc.response is not None:
            detail = f" {exc.response.status_code}: {exc.response.text[:120]}"
        print(f"SKIP {model}: {type(exc).__name__}{detail}", flush=True)
        return False


def main() -> None:
    golden = [json.loads(ln) for ln in
              (ROOT / "eval" / "golden_set" / "v1.jsonl").read_text().split("\n") if ln.strip()]
    cases = [g for g in golden if g["id"] in CHECKS]
    now_str = now_berlin().strftime("%A, %d. %B %Y, %H:%M")

    models = [m for m in MODELS if model_available(m)]
    print(f"models available: {models}", flush=True)

    results: dict[str, dict] = {}
    for variant in VARIANTS:
        prompt = (ROOT / "eval" / "prompts" / f"{variant}.txt").read_text().replace("{NOW}", now_str)
        for model in models:
            key = f"{variant} × {model.split('/')[-1]}"
            passed, details, tok_total, ms_total, usd_total = 0, [], 0, 0.0, 0.0
            for g in cases:
                system = prompt
                if g["id"] == "q21":
                    system += "\nUSER PROFILE: prefers electronic music, Kiez: Friedrichshain."
                try:
                    action, tokens, ms, usd = chat_call(model, system, g["query"])
                    fails = CHECKS[g["id"]](action)
                except Exception as exc:
                    fails = [f"call failed: {type(exc).__name__}"]
                    tokens, ms, usd = 0, 0.0, 0.0
                tok_total += tokens
                ms_total += ms
                usd_total += usd
                passed += not fails
                details.append({"qid": g["id"], "pass": not fails, "fails": fails})
            results[key] = {
                "variant": variant, "model": model,
                "score": round(passed / len(cases), 3),
                "passed": passed, "of": len(cases),
                "tokens": tok_total, "mean_ms": round(ms_total / len(cases)),
                "usd_total": round(usd_total, 6),
                "usd_per_turn": round(usd_total / len(cases), 6),
                "details": details,
            }
            print(f"{key:48} {passed}/{len(cases)} ({results[key]['score']:.0%})  "
                  f"{results[key]['mean_ms']}ms/turn  ${results[key]['usd_per_turn']:.5f}/turn",
                  flush=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    (ROOT / "eval" / "results" / f"prompts-{stamp}.json").write_text(json.dumps({
        "experiment": "3-prompt-techniques-stage1", "golden_set": "v1",
        "kind": "tool-call accuracy (deterministic asserts, no execution)",
        "models": models, "variants": VARIANTS, "results": results}, indent=2))

    md = ["# Prompt benchmark — Experiment 3, stage 1 (tool-call accuracy)", "",
          "First model action asserted deterministically per golden chat query: right tool, "
          "right args, dates resolved — or correctly NO tool (chitchat/ambiguous). "
          "No execution, no judge (that's stage 2). Cost = measured USD per turn "
          "(OpenRouter usage accounting).", "",
          "| variant × model | score | ms/turn | $/turn |", "|---|---|---|---|"]
    for k, r in results.items():
        md.append(f"| {k} | {r['passed']}/{r['of']} ({r['score']:.0%}) | {r['mean_ms']} "
                  f"| {r['usd_per_turn']:.5f} |")
    md += ["", "## Failures", ""]
    for k, r in results.items():
        fails = [d for d in r["details"] if not d["pass"]]
        if fails:
            md.append(f"**{k}**: " + "; ".join(f"{d['qid']} ({', '.join(d['fails'])})" for d in fails))
    (ROOT / "docs" / "prompt-benchmark.md").write_text("\n".join(md) + "\n")
    print("\nwrote docs/prompt-benchmark.md")


if __name__ == "__main__":
    main()
