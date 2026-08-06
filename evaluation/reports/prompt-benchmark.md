# Prompt benchmark — Experiment 3, stage 1 (tool-call accuracy)

First model action asserted deterministically per golden chat query: right tool, right args, dates resolved — or correctly NO tool (chitchat/ambiguous). No execution, no judge (that's stage 2). Cost = measured USD per turn (OpenRouter usage accounting).

| variant × model | score | ms/turn | $/turn |
|---|---|---|---|
| zero-shot × claude-haiku-4.5 | 10/13 (77%) | 2149 | 0.00167 |
| zero-shot × gpt-4o-mini | 10/13 (77%) | 1211 | 0.00007 |
| zero-shot × gemini-2.5-flash | 10/13 (77%) | 743 | 0.00015 |
| zero-shot × deepseek-v4-flash | 9/13 (69%) | 6283 | 0.00009 |
| zero-shot × deepseek-v4-pro | 10/13 (77%) | 5425 | 0.00145 |
| zero-shot × minimax-m2.7 | 11/13 (85%) | 4189 | 0.00033 |
| zero-shot × glm-5.2 | 10/13 (77%) | 3539 | 0.00083 |
| zero-shot × gemma-4-31b-it | 11/13 (85%) | 1741 | 0.00006 |
| zero-shot × gpt-4.1-nano | 11/13 (85%) | 2168 | 0.00007 |
| prod-v1 × claude-haiku-4.5 | 10/13 (77%) | 2081 | 0.00206 |
| prod-v1 × gpt-4o-mini | 9/13 (69%) | 1153 | 0.00012 |
| prod-v1 × gemini-2.5-flash | 12/13 (92%) | 841 | 0.00027 |
| prod-v1 × deepseek-v4-flash | 9/13 (69%) | 6693 | 0.00008 |
| prod-v1 × deepseek-v4-pro | 10/13 (77%) | 13667 | 0.00214 |
| prod-v1 × minimax-m2.7 | 9/13 (69%) | 5570 | 0.00037 |
| prod-v1 × glm-5.2 | 11/13 (85%) | 3617 | 0.00088 |
| prod-v1 × gemma-4-31b-it | 11/13 (85%) | 1743 | 0.00009 |
| prod-v1 × gpt-4.1-nano | 12/13 (92%) | 2881 | 0.00013 |
| few-shot × claude-haiku-4.5 | 12/13 (92%) | 2045 | 0.00224 |
| few-shot × gpt-4o-mini | 12/13 (92%) | 1431 | 0.00016 |
| few-shot × gemini-2.5-flash | 8/13 (62%) | 963 | 0.00038 |
| few-shot × deepseek-v4-flash | 11/13 (85%) | 6924 | 0.00011 |
| few-shot × deepseek-v4-pro | 12/13 (92%) | 8298 | 0.00150 |
| few-shot × minimax-m2.7 | 12/13 (92%) | 6676 | 0.00042 |
| few-shot × glm-5.2 | 11/13 (85%) | 3380 | 0.00088 |
| few-shot × gemma-4-31b-it | 12/13 (92%) | 1800 | 0.00012 |
| few-shot × gpt-4.1-nano | 12/13 (92%) | 2742 | 0.00015 |
| clarify-first × claude-haiku-4.5 | 4/13 (31%) | 2441 | 0.00193 |
| clarify-first × gpt-4o-mini | 6/13 (46%) | 1082 | 0.00011 |
| clarify-first × gemini-2.5-flash | 6/13 (46%) | 998 | 0.00025 |
| clarify-first × deepseek-v4-flash | 9/13 (69%) | 5566 | 0.00008 |
| clarify-first × deepseek-v4-pro | 9/13 (69%) | 8239 | 0.00061 |
| clarify-first × minimax-m2.7 | 9/13 (69%) | 7028 | 0.00045 |
| clarify-first × glm-5.2 | 9/13 (69%) | 3455 | 0.00092 |
| clarify-first × gemma-4-31b-it | 5/13 (38%) | 2716 | 0.00010 |
| clarify-first × gpt-4.1-nano | 4/13 (31%) | 1408 | 0.00008 |

## Failures

**zero-shot × claude-haiku-4.5**: q07 (called search_events); q14 (geo params, Neukölln or Schillerkiez query); q23 (date_from = tomorrow evening, live-music intent in query/subcategory)
**zero-shot × gpt-4o-mini**: q07 (semantic query set (vibe needs ranking)); q14 (geo params, Neukölln or Schillerkiez query); q23 (live-music intent in query/subcategory)
**zero-shot × gemini-2.5-flash**: q07 (called search_events); q14 (geo params, Neukölln or Schillerkiez query); q19 (attempted a search)
**zero-shot × deepseek-v4-flash**: q07 (semantic query set (vibe needs ranking)); q14 (geo params, Neukölln or Schillerkiez query); q18 (no tool before clarifying, asked a clarifying question); q23 (date_from = tomorrow evening, live-music intent in query/subcategory)
**zero-shot × deepseek-v4-pro**: q14 (geo params, Neukölln or Schillerkiez query); q18 (no tool before clarifying, asked a clarifying question); q23 (date_from = tomorrow evening, live-music intent in query/subcategory)
**zero-shot × minimax-m2.7**: q14 (called search_events); q23 (date_from = tomorrow evening, live-music intent in query/subcategory)
**zero-shot × glm-5.2**: q07 (semantic query set (vibe needs ranking)); q18 (no tool before clarifying, asked a clarifying question); q23 (live-music intent in query/subcategory)
**zero-shot × gemma-4-31b-it**: q14 (geo params, Neukölln or Schillerkiez query); q23 (date_from = tomorrow evening)
**zero-shot × gpt-4.1-nano**: q16 (date window covers Sunday); q23 (date_from = tomorrow evening)
**prod-v1 × claude-haiku-4.5**: q14 (geo params, Neukölln or Schillerkiez query); q16 (date window covers Sunday); q23 (date_from = tomorrow evening)
**prod-v1 × gpt-4o-mini**: q07 (semantic query set (vibe needs ranking)); q14 (geo params, Neukölln or Schillerkiez query); q18 (no tool before clarifying, asked a clarifying question); q23 (live-music intent in query/subcategory)
**prod-v1 × gemini-2.5-flash**: q14 (geo params, Neukölln or Schillerkiez query)
**prod-v1 × deepseek-v4-flash**: q07 (semantic query set (vibe needs ranking)); q18 (no tool before clarifying, asked a clarifying question); q23 (date_from = tomorrow evening); q25 (family_friendly=true)
**prod-v1 × deepseek-v4-pro**: q07 (semantic query set (vibe needs ranking)); q18 (no tool before clarifying, asked a clarifying question); q23 (date_from = tomorrow evening, live-music intent in query/subcategory)
**prod-v1 × minimax-m2.7**: q07 (semantic query set (vibe needs ranking)); q11 (free_entry=true); q18 (no tool before clarifying, asked a clarifying question); q23 (date_from = tomorrow evening, live-music intent in query/subcategory)
**prod-v1 × glm-5.2**: q18 (no tool before clarifying, asked a clarifying question); q23 (live-music intent in query/subcategory)
**prod-v1 × gemma-4-31b-it**: q14 (geo params, Neukölln or Schillerkiez query); q18 (no tool before clarifying, asked a clarifying question)
**prod-v1 × gpt-4.1-nano**: q18 (no tool before clarifying, asked a clarifying question)
**few-shot × claude-haiku-4.5**: q16 (date window covers Sunday)
**few-shot × gpt-4o-mini**: q18 (no tool before clarifying, asked a clarifying question)
**few-shot × gemini-2.5-flash**: q07 (called search_events); q17 (searched first (answer-first policy)); q23 (called search_events); q24 (called search_events); q25 (called search_events)
**few-shot × deepseek-v4-flash**: q18 (no tool before clarifying, asked a clarifying question); q25 (family_friendly=true)
**few-shot × deepseek-v4-pro**: q18 (no tool before clarifying, asked a clarifying question)
**few-shot × minimax-m2.7**: q23 (live-music intent in query/subcategory)
**few-shot × glm-5.2**: q18 (no tool before clarifying, asked a clarifying question); q23 (live-music intent in query/subcategory)
**few-shot × gemma-4-31b-it**: q18 (no tool before clarifying, asked a clarifying question)
**few-shot × gpt-4.1-nano**: q18 (no tool before clarifying, asked a clarifying question)
**clarify-first × claude-haiku-4.5**: q07 (called search_events); q11 (called search_events); q14 (called search_events); q16 (called search_events); q17 (searched first (answer-first policy)); q21 (called search_events); q23 (called search_events); q24 (called search_events); q25 (called search_events)
**clarify-first × gpt-4o-mini**: q07 (called search_events); q11 (called search_events); q14 (geo params, Neukölln or Schillerkiez query); q17 (searched first (answer-first policy)); q21 (called search_events); q23 (called search_events); q25 (called search_events)
**clarify-first × gemini-2.5-flash**: q07 (called search_events); q14 (called search_events); q16 (called search_events); q17 (searched first (answer-first policy)); q19 (attempted a search); q23 (called search_events); q24 (called search_events)
**clarify-first × deepseek-v4-flash**: q07 (called search_events); q17 (searched first (answer-first policy)); q23 (date_from = tomorrow evening, live-music intent in query/subcategory); q25 (family_friendly=true)
**clarify-first × deepseek-v4-pro**: q07 (called search_events); q17 (searched first (answer-first policy)); q23 (date_from = tomorrow evening); q25 (family_friendly=true)
**clarify-first × minimax-m2.7**: q07 (called search_events); q17 (searched first (answer-first policy)); q23 (live-music intent in query/subcategory); q25 (called search_events)
**clarify-first × glm-5.2**: q07 (called search_events); q17 (searched first (answer-first policy)); q23 (live-music intent in query/subcategory); q25 (date window covers the weekend)
**clarify-first × gemma-4-31b-it**: q07 (called search_events); q14 (called search_events); q16 (called search_events); q17 (searched first (answer-first policy)); q21 (called search_events); q23 (called search_events); q24 (called search_events); q25 (called search_events)
**clarify-first × gpt-4.1-nano**: q07 (called search_events); q11 (called search_events); q14 (called search_events); q16 (called search_events); q17 (searched first (answer-first policy)); q21 (called search_events); q23 (called search_events); q24 (called search_events); q25 (called search_events)
