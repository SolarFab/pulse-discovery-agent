# Embedding benchmark — hand-labeled qrels (golden set v1, frozen corpus v1)

Human relevance labels over pooled candidates; K=5. Queries with no relevant event in pool: q05, q11, q12.

| model | recall@5 | precision@5 | MRR | nDCG@5 | queries |
|---|---|---|---|---|---|
| openai/text-embedding-3-small | 0.621 | 0.585 | 0.896 | 0.729 | 13 |
| qwen/qwen3-embedding-8b | 0.248 | 0.262 | 0.646 | 0.337 | 13 |
