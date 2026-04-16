#!/usr/bin/env bash
set -euo pipefail
export OPENAI_API_KEY='ak-91d2efgh67i4jkl82mno53pqrs76tuv3m8'

INPUT_PREFIX='s3://stepdata-text/haibao/designcap/'
OUT_BASE='/data/openclaw/poster-reverse-query/out/compare_20260414_v2_v3'

python /data/openclaw/poster-reverse-query/run_poster_prompt_v2_smoke_test.py \
  --input-prefix "$INPUT_PREFIX" \
  --output-dir "$OUT_BASE/v2" \
  --limit 10 \
  --model gpt-4.1-mini

python /data/openclaw/poster-reverse-query/run_poster_prompt_v3_smoke_test.py \
  --input-prefix "$INPUT_PREFIX" \
  --output-dir "$OUT_BASE/v3" \
  --limit 10 \
  --model gpt-4.1-mini
