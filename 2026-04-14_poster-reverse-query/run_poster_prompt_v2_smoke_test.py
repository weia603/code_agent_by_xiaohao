#!/usr/bin/env python3
"""Run poster_prompt_v2 on a small batch of poster/infographic schema summaries.
Required args: --input-path/--input-prefix, --output-dir, --api-key-env. Streaming + checkpointed JSONL writes to avoid OOM.
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from build_poster_reverse_query_pairs import (
    KeyPool,
    call_llm,
    iter_input_paths,
    load_processed_ids,
    summarize_schema,
)
from megfile import smart_open


PROMPT_FILE = Path(__file__).resolve().parent / 'poster_prompt_v2.md'


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-path', action='append', default=[], help='Single S3/local json path; repeatable')
    ap.add_argument('--input-prefix', action='append', default=[], help='S3/local prefix to scan for .json files; repeatable')
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--api-key-env', default='OPENAI_API_KEY')
    ap.add_argument('--model', default='gpt-4.1-mini')
    ap.add_argument('--rpm', type=int, default=60)
    ap.add_argument('--concurrency', type=int, default=1)
    ap.add_argument('--timeout-sec', type=int, default=120)
    ap.add_argument('--max-tokens', type=int, default=2200)
    ap.add_argument('--temperature', type=float, default=0.2)
    ap.add_argument('--resume-result-file', default='')
    ap.add_argument('--limit', type=int, default=5)
    ap.add_argument('--sleep-sec', type=float, default=0.0, help='Optional sleep between samples to reduce burstiness')
    return ap.parse_args()


async def main_async():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = PROMPT_FILE.read_text(encoding='utf-8')

    api_keys_raw = os.getenv(args.api_key_env, '').strip()
    if not api_keys_raw:
        raise ValueError(f'Missing API keys in env: {args.api_key_env}')
    api_keys = [x.strip() for x in api_keys_raw.split(',') if x.strip()]
    key_pool = KeyPool(api_keys, rpm=args.rpm)

    processed = load_processed_ids(args.resume_result_file)
    ts = time.strftime('%Y%m%d_%H%M%S')
    result_path = output_dir / f'result_poster_prompt_v2_smoke_{ts}.jsonl'
    error_path = output_dir / f'errors_poster_prompt_v2_smoke_{ts}.jsonl'
    stats_path = output_dir / f'stats_poster_prompt_v2_smoke_{ts}.json'

    scanned = 0
    enqueued = 0
    skipped_done = 0
    parse_failed = 0

    import build_poster_reverse_query_pairs as build_mod
    original_system = build_mod.SYSTEM_PROMPT
    original_user_template = build_mod.USER_TEMPLATE
    try:
        system_split = '## User prompt template'
        if system_split in prompt_text:
            system_part, user_part = prompt_text.split(system_split, 1)
            build_mod.SYSTEM_PROMPT = system_part.replace('# poster_prompt_v2', '').replace('## System prompt', '').strip()
            build_mod.USER_TEMPLATE = user_part.replace('## User prompt template', '').strip()

        with result_path.open('a', encoding='utf-8') as result_f, error_path.open('a', encoding='utf-8') as error_f:
            for path in iter_input_paths(args):
                if args.limit and scanned >= args.limit:
                    break
                scanned += 1
                try:
                    with smart_open(path, 'r', encoding='utf-8') as f:
                        root = json.load(f)
                except Exception as e:
                    parse_failed += 1
                    error_f.write(json.dumps({'source_path': path, 'stage': 'parse', 'error': repr(e)}, ensure_ascii=False) + '\n')
                    error_f.flush()
                    continue

                summary = summarize_schema(path, root)
                sample_id = summary['sample_id']
                if sample_id in processed:
                    skipped_done += 1
                    continue

                try:
                    llm_out = await call_llm(summary, args, key_pool)
                    rec = {
                        'sample_id': sample_id,
                        'source_path': path,
                        'prompt_name': 'poster_prompt_v2',
                        'prompt_file': str(PROMPT_FILE),
                        'schema_summary': summary,
                        'reverse_query_result': llm_out,
                    }
                    result_f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                    result_f.flush()
                    enqueued += 1
                    if args.sleep_sec > 0:
                        await asyncio.sleep(args.sleep_sec)
                except Exception as e:
                    error_f.write(json.dumps({
                        'sample_id': sample_id,
                        'source_path': path,
                        'prompt_name': 'poster_prompt_v2',
                        'schema_summary': summary,
                        'error': repr(e),
                    }, ensure_ascii=False) + '\n')
                    error_f.flush()
                    if args.sleep_sec > 0:
                        await asyncio.sleep(args.sleep_sec)
    finally:
        build_mod.SYSTEM_PROMPT = original_system
        build_mod.USER_TEMPLATE = original_user_template

    stats = {
        'prompt_name': 'poster_prompt_v2',
        'prompt_file': str(PROMPT_FILE),
        'scanned': scanned,
        'processed': enqueued,
        'skipped_done': skipped_done,
        'parse_failed': parse_failed,
        'result_path': str(result_path),
        'error_path': str(error_path),
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({**stats, 'stats_path': str(stats_path)}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main_async())
