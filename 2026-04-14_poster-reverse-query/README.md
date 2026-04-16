# poster-reverse-query

Poster / infographic reverse-query generation workspace.

## Current files

- `build_poster_reverse_query_pairs.py` — main batch builder for reverse query generation
- `poster_prompt_v1.md` — v1 prompt for reverse query generation
- `poster_eval_rubric.md` — review rubric for prompt output quality
- `run_poster_prompt_v1_smoke_test.py` — small-batch smoke test runner for prompt iteration
- `poster_config.sample.json` — sample config for the poster task
- `sample_training_pair_extreme_sports.md` — one manual sample for reference

## Recommended workflow

### Phase 1: prompt iteration

Run a very small smoke test first, review outputs manually, then refine prompt.

Example:

```bash
export OPENAI_API_KEY=your_key_here
python /data/openclaw/poster-reverse-query/run_poster_prompt_v1_smoke_test.py \
  --input-path s3://stepdata-text/haibao/designcap/11bd242dee2b4cd081a21d75da298f09/11bd242dee2b4cd081a21d75da298f09.json \
  --output-dir /data/openclaw/poster-reverse-query/out/smoke \
  --limit 5
```

Outputs:
- `result_poster_prompt_v1_smoke_*.jsonl`
- `errors_poster_prompt_v1_smoke_*.jsonl`
- `stats_poster_prompt_v1_smoke_*.json`

Use `poster_eval_rubric.md` for manual review.

### Phase 2: revise prompt

Common failure modes to inspect:
- topic-only queries
- caption-like outputs
- schema leakage
- hallucinated business context
- overly generic wording

After reviewing samples, revise `poster_prompt_v1.md` into `poster_prompt_v2.md` if needed.

### Phase 3: scale batch generation

Once prompt quality is stable, run the batch builder:

```bash
export OPENAI_API_KEY=your_key_here
python /data/openclaw/poster-reverse-query/build_poster_reverse_query_pairs.py \
  --input-prefix s3://stepdata-text/haibao/designcap/ \
  --output-dir /data/openclaw/poster-reverse-query/out/full_run \
  --concurrency 8 \
  --rpm 60
```

## Notes

- The pipeline is streaming + checkpoint-friendly.
- Results are written incrementally as JSONL.
- Prompt should stay at requirement level, not schema-coordinate level.
- Keep naming task-scoped with `poster_*` prefixes for prompt and rubric assets.
