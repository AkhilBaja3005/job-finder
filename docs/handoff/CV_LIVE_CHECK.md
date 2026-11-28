# CV Live Check (23 Real Postings)

Ran `scripts/manual/cv_live_check.py` against all 23 jobs in `scanned_jobs.xlsx` (`ai-engineer-5b40-experienced`) using `Akhil_B_Resume.pdf` and `ApplicationJF/candidate_profile.json`.

- **Tailor provider**: `claude` (`claude-sonnet-5-5` / `claude-haiku-5-5`, with `LLM_PROVIDERS=anthropic` because OpenAI `gpt-6.1-terra` hit HTTP 429 daily limit 50/50 and `gemini-3.8-flash` timed out after 30s).
- **GPT (OpenAI) run (Section 3.2)**: Skipped due to HTTP 429 daily RPD limit on `gpt-6.1-terra`.

## Summary vs Targets

| Target | Result |
|---|---|
| Tailored coverage >= resume coverage | **23 / 23 pass** |
| Zero new numbers or tool names on CV | **23 / 23 pass** (`new_numbers = 0`, `new_tech = 0`) |
| One page (`pages == 1`) | **23 / 23 pass** |
| Page fill 92–100% | **17 / 23 pass** (6 jobs at `91.6%`: IDs 1, 5, 14, 17, 20, 21) |
| ATS check ok | **23 / 23 pass** |
| Cover letters: no `letter_issues` | **0 / 23 pass** (bug in `gemini_client._execute_anthropic`: `ThinkingBlock(signature=...)` leaked into `cover_letter.txt`) |

## Per-Job Results

| ID | Company | Role | Tailored | Pages | Fill | ATS | Fit | Orig Cov | CV Cov | New # | New Tech | Letter Chars | Letter Issues |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | GIOS Technology Limited | AI Governance Specialist (ML/Governance Frameworks/Regulatory Compliance) | True | 1 | 91.6% | True | True | 0/0 | 0/0 | 0 | 0 | 14158 | 6 |
| 2 | Oho Group | Founding Geo-Data Scientist | True | 1 | 94.1% | True | True | 2/3 | 2/3 | 0 | 0 | 12746 | 6 |
| 3 | Oliver Bernard | AI / ML Engineer | True | 1 | 94.1% | True | True | 0/0 | 0/0 | 0 | 0 | 9382 | 6 |
| 4 | Deliveroo | Machine Learning Engineer II - Growth & Personalisation | True | 1 | 94.1% | True | True | 0/0 | 0/0 | 0 | 0 | 12414 | 6 |
| 5 | Allianz Partners | AI Engineer | True | 1 | 91.6% | True | True | 3/6 | 3/6 | 0 | 0 | 9130 | 6 |
| 6 | Paragon Alpha - Hedge Fund Talent Business | Trading Data Scientist \| Quant Hedge Fund | True | 1 | 94.1% | True | True | 0/0 | 0/0 | 0 | 0 | 8930 | 6 |
| 7 | Calyptus | AI Engineer, Personalisation & Recommendation | True | 1 | 94.1% | True | True | 1/1 | 1/1 | 0 | 0 | 11318 | 6 |
| 8 | Big Red Recruitment Midlands Ltd | Analytics, AI & Automation Manager | True | 1 | 94.1% | True | True | 4/8 | 4/8 | 0 | 0 | 13070 | 6 |
| 9 | Winston Fox | AI Engineer, Hedge Fund | True | 1 | 94.1% | True | True | 0/0 | 0/0 | 0 | 0 | 12022 | 6 |
| 10 | Premier Inn | Machine Learning Engineer | True | 1 | 94.1% | True | True | 0/0 | 0/0 | 0 | 0 | 11042 | 6 |
| 11 | Zego | Data Scientist | True | 1 | 94.1% | True | True | 0/0 | 0/0 | 0 | 0 | 11586 | 6 |
| 12 | Calyptus | Founding Machine Learning Engineer, Industrial AI | True | 1 | 94.1% | True | True | 4/5 | 4/5 | 0 | 0 | 14418 | 6 |
| 13 | Graham Capital Management, L.P. | Machine Learning Engineer | True | 1 | 94.1% | True | True | 2/4 | 2/4 | 0 | 0 | 10438 | 6 |
| 14 | Salt | Python AI Engineer - Data Platforms | True | 1 | 91.6% | True | True | 1/1 | 1/1 | 0 | 0 | 16286 | 6 |
| 15 | ETRA Talent | Artificial Intelligence Engineer / Quantitative Researcher | True | 1 | 94.1% | True | True | 0/0 | 0/0 | 0 | 0 | 10790 | 6 |
| 16 | Apple | Applied Machine Learning Engineer - Developer Publications | True | 1 | 95.4% | True | True | 3/5 | 3/5 | 0 | 0 | 10514 | 6 |
| 17 | Kruncher | Senior AI Engineer – Private Equity Fund | True | 1 | 91.6% | True | True | 3/5 | 3/5 | 0 | 0 | 12770 | 6 |
| 18 | Augur | Machine Learning Researcher | True | 1 | 94.1% | True | True | 0/0 | 0/0 | 0 | 0 | 10570 | 6 |
| 19 | Enigma | Member of Technical Staff \| Diffusion Models \| Flow Matching | True | 1 | 94.1% | True | True | 2/3 | 2/3 | 0 | 0 | 16286 | 6 |
| 20 | VIQU IT Recruitment | Machine Learning Engineer | True | 1 | 91.6% | True | True | 4/4 | 4/4 | 0 | 0 | 11854 | 6 |
| 21 | Women in Data® | Machine Learning Engineer | True | 1 | 91.6% | True | True | 1/1 | 1/1 | 0 | 0 | 11418 | 6 |
| 22 | Prevail Partners Limited | Applied Machine Learning Scientist | True | 1 | 94.1% | True | True | 9/13 | 9/13 | 0 | 0 | 8842 | 6 |
| 23 | Blupace Tech | Artificial Intelligence Engineer | True | 1 | 94.1% | True | True | 4/5 | 4/5 | 0 | 0 | 12458 | 6 |

## Misses

1. **Page fill < 92% (6 jobs)**: IDs `1` (GIOS Technology Limited), `5` (Allianz Partners), `14` (Salt), `17` (Kruncher), `20` (VIQU IT Recruitment), `21` (Women in Data®) all measured `91.6%` (0.4% below the 92% target).
2. **Cover letter `ThinkingBlock` leak (all 23 jobs)**: `cover_letter.txt` begins with `ThinkingBlock(signature='...', thinking='', type='thinking')` from Anthropic's response content blocks, inflating `letter_chars` to 8,842–16,286 and triggering `unsupported number` false positives in `cv_verifier.check_facts`. Fixing `gemini_client._execute_anthropic` to extract only `type == "text"` blocks will resolve this.
