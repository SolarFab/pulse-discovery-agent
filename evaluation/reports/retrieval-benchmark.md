# Retrieval benchmark — Experiment 2 (frozen corpus v1, qrels v1)

Latency = per-query wall time incl. any LLM expansion (chat hot path budget ~2s). `unlabeled@5` = top-5 results outside the labeled pool, scored irrelevant until the delta labeling round (pool bias, reported honestly).

| config | recall@5 | precision@5 | MRR | nDCG@5 | ms/query | LLM tokens | unlabeled@5 |
|---|---|---|---|---|---|---|---|
| baseline | 0.621 | 0.585 | 0.896 | 0.729 | 748 | 0 | 0 |
| bm25 | 0.392 | 0.323 | 0.546 | 0.38 | 1 | 0 | 0 |
| hybrid | 0.458 | 0.415 | 0.755 | 0.542 | 707 | 0 | 0 |
| mq | 0.531 | 0.492 | 0.653 | 0.54 | 1164 | 1044 | 0 |
| hyde | 0.37 | 0.415 | 0.596 | 0.428 | 702 | 1997 | 0 |
