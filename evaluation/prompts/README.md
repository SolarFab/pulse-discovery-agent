# The four prompt variants

These are the literal files `scripts/benchmark_prompts.py` loops over. `{NOW}` is substituted
with a fixed Berlin timestamp so that "tonight" and "am Sonntag" resolve identically for every
model and every run.

| file | lines | what it adds |
|---|---|---|
| `zero-shot.txt` | 5 | Role, current time, tool names. The control. |
| `prod-v1.txt` | 18 | What shipped at the time: grounding rules, date handling, style. Instructions, no examples. |
| `clarify-first.txt` | 18 | prod-v1, but told to ask a clarifying question when the request is ambiguous. |
| **`few-shot.txt`** | 25 | **prod-v1 plus five worked examples** mapping a question to a concrete tool call. The winner. |

`prod-v1` and `few-shot` differ *only* by those five examples — that is what isolates the variable.

## These files are frozen, and one of them is now wrong on purpose

`few-shot.txt` scored 92% and shipped. Its first worked example was:

```
"Jazz heute Abend?" → search_events({ query: "jazz", subcategory: "jazz-blues", … })
```

That example later turned out to be **the direct cause of a production incident**: it taught the
model to put a music genre into `subcategory`, which is a strict SQL filter over a column that is
~6% mislabelled and, for `comedy`, was 99.5% empty. Correct events were filtered out before the
embedding could rank them. The full autopsy is in `../reports/CONCIERGE-FINDINGS.md`.

**The file is deliberately not corrected.** It is the record of what was measured; editing it
would attach a real score to a prompt that was never actually run. The 92% belongs to this text.

The **live** prompt has since been changed — see `../concierge/route.ts`, where example 1 now puts
genre in `query` and reserves `subcategory` for explicit format requests. So the two files differ,
and that difference is the finding, not a mistake.

**The uncomfortable implication:** the benchmark scored this prompt 92% and the score was correct
by its own definition — the checks tested whether the model *did what the prompt asked*. Nothing
in the harness could tell that what the prompt asked for was itself wrong. An eval measures
compliance with your intent; it cannot tell you your intent is bad. That took a user reporting a
missing comedy show.
