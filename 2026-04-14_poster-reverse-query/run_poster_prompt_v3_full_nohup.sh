#!/usr/bin/env bash
# Full poster reverse-query run.
# Streaming + checkpointed JSONL writes to avoid OOM.
set -euo pipefail

export XDG_CACHE_HOME=/data/.cache
export PLAYWRIGHT_BROWSERS_PATH=/data/.cache/ms-playwright
export PUPPETEER_CACHE_DIR=/data/.cache/puppeteer
export npm_config_cache=/data/.cache/npm
export TMPDIR=/data/tmp
mkdir -p /data/.cache /data/.cache/ms-playwright /data/.cache/puppeteer /data/.cache/npm /data/tmp

export OPENAI_API_KEY='ak-91d2efgh67i4jkl82mno53pqrs76tuv3m8,ak-79h1ijkl23m4nop56qrst78uvwx90yz12b3,ak-93hd7vke42mj1qpl85nsty60wzxuafbci7'

RUN_ROOT='/data/openclaw/poster-reverse-query/out/full_v3_20260414'
mkdir -p "$RUN_ROOT"

python /data/openclaw/poster-reverse-query/run_poster_prompt_v3_smoke_test.py \
  --input-prefix s3://stepdata-text/haibao/designcap/ \
  --output-dir "$RUN_ROOT" \
  --model gpt-4.1-mini \
  --rpm 180 \
  --concurrency 24 \
  --timeout-sec 120 \
  --max-tokens 2200 \
  --temperature 0.2 \
  --sleep-sec 0.0 \
  --limit 0
