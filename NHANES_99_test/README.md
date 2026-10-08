# NHANES 99 — a small evaluation set

99 questions taken from the NHANES portion of
[LongDA](https://arxiv.org/abs/2601.02598) (`EvilBench/LongDA` on Hugging Face),
with the published answers kept in a separate file.

| file | |
|---|---|
| `questions.csv` | the questions, with the definitions each one requires |
| `answer_key.csv` | the published values, one row per question |

The raw NHANES files are **not** included — they are public and large. Download
them from [CDC NHANES](https://wwwn.cdc.gov/nchs/nhanes/) (August 2021–August 2023
cycle) or via the LongDA dataset.

Answers come from NCHS Data Briefs, which report **survey-weighted national
estimates**. Unweighted figures will not match. Use `WTMEC2YR` (examination) or
`WTINT2YR` (interview) with `SDMVSTRA` and `SDMVPSU`, and apply the weight to
the full file before subsetting.

The LongDA paper scores an answer correct when `|predicted − actual| ≤
max(0.05·|actual|, 1)`, element-wise for list answers, with no partial credit.
