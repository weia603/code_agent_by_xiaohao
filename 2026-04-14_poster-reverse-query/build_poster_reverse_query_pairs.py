#!/usr/bin/env python3
"""Build reverse-query training pairs from DesignCap-style poster/infographic S3 JSONs.
Required args: --input-path / --input-prefix, --output-dir, --api-key-env. Streaming + checkpointed JSONL writes to avoid OOM.
"""

import argparse
import asyncio
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from itertools import cycle
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from megfile import smart_open, smart_walk
from step_align.model.proxy import async_chat_completion

SYSTEM_PROMPT = """You are generating reverse design queries for poster / infographic training data.
Given a structured design schema summary, write a natural user query that asks for that design.
The query must contain:
1. the topic / what the poster or infographic is about
2. design requirements / how to design it, including style, tone, color direction, layout intent, and content organization when supported by the schema
Rules:
- Stay at the requirement level, not exact implementation coordinates.
- Do not mention exact x/y positions, element ids, asset keys, crop numbers, page pixel sizes, or internal schema fields.
- Do not hallucinate business facts unsupported by the schema.
- Prefer natural product-facing wording.
- Output valid JSON only.
"""

USER_TEMPLATE = """Generate one reverse-query training sample from this schema summary.
Return JSON with keys:
- suitability: one of [strong, medium, weak]
- reasoning: short string
- semantic_brief: object with concise extracted fields
- query: the reverse-generated user query in Chinese
- query_en: optional English query if the source content is clearly English-first
- negative_constraints: array of strings describing what should NOT be leaked from schema to query

Schema summary JSON:
{schema_summary}
"""


@dataclass
class RateLimiter:
    rpm: int

    def __post_init__(self):
        self.interval = 60.0 / max(self.rpm, 1)
        self._lock = asyncio.Lock()
        self._next_ts = 0.0

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            if now < self._next_ts:
                await asyncio.sleep(self._next_ts - now)
                now = time.monotonic()
            self._next_ts = max(now, self._next_ts) + self.interval


class KeyPool:
    def __init__(self, keys: List[str], rpm: int):
        self.keys = keys
        self._cycler = cycle(range(len(keys)))
        self.limiters = [RateLimiter(rpm=rpm) for _ in keys]
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            idx = next(self._cycler)
        return self.keys[idx], self.limiters[idx]


def iter_json_paths(prefix: str) -> Iterable[str]:
    for root, _dirs, files in smart_walk(prefix):
        for fn in files:
            if fn.lower().endswith('.json'):
                yield root.rstrip('/') + '/' + fn


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-path', action='append', default=[], help='Single S3/local json path; repeatable')
    ap.add_argument('--input-prefix', action='append', default=[], help='S3/local prefix to scan for .json files; repeatable')
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--api-key-env', default='OPENAI_API_KEY')
    ap.add_argument('--model', default='gpt-4.1-mini')
    ap.add_argument('--rpm', type=int, default=60)
    ap.add_argument('--concurrency', type=int, default=8)
    ap.add_argument('--timeout-sec', type=int, default=120)
    ap.add_argument('--max-tokens', type=int, default=2200)
    ap.add_argument('--temperature', type=float, default=0.2)
    ap.add_argument('--resume-result-file', default='')
    ap.add_argument('--limit', type=int, default=0)
    return ap.parse_args()


def normalize_text(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip())


def collect_text_blocks(page: Dict[str, Any]) -> List[str]:
    out = []
    for g in page.get('graphs', []):
        if g.get('graphType') == 'Text':
            txt = normalize_text(g.get('text', ''))
            if txt:
                out.append(txt)
    return out


def infer_color_palette(pages: List[Dict[str, Any]]) -> List[str]:
    c = Counter()
    def add_color(x):
        if isinstance(x, str) and x.startswith('#'):
            c[x.upper()] += 1
    for page in pages:
        bg = page.get('background', {})
        for k in ['color1', 'gradientColor1', 'gradientColor2']:
            add_color(bg.get(k))
        for g in page.get('graphs', []):
            add_color(g.get('fontColor'))
            add_color(g.get('fillColor'))
            for cc in g.get('colors', []) or []:
                add_color(cc)
    return [x for x, _ in c.most_common(8)]


def infer_format(root: Dict[str, Any]) -> str:
    category = (root.get('category') or '').lower()
    pages = root.get('pages', []) or []
    if category == 'infographic' or root.get('canvas_layout_mode') == 'continuous' or len(pages) >= 3:
        return 'long_form_infographic'
    return 'poster'


def infer_layout_traits(root: Dict[str, Any]) -> List[str]:
    pages = root.get('pages', []) or []
    traits = []
    if root.get('canvas_layout_mode') == 'continuous' or root.get('canvasLayoutMode') == 'continuous':
        traits.append('continuous vertical layout')
    if len(pages) >= 2:
        traits.append('multi-section structure')
    if pages:
        first_texts = collect_text_blocks(pages[0])
        if any(len(t) < 80 for t in first_texts[:3]):
            traits.append('hero cover with prominent title')
    if any(sum(1 for g in p.get('graphs', []) if g.get('graphType') == 'Photo') >= 2 for p in pages):
        traits.append('image-and-text mixed sections')
    return traits


def unwrap_designcap_root(root: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(root, dict) and isinstance(root.get('data'), dict):
        data = root['data']
        if any(k in data for k in ['pages', 'category', 'key', 'name']):
            return data
    return root


def summarize_schema(path: str, root: Dict[str, Any]) -> Dict[str, Any]:
    root = unwrap_designcap_root(root)
    pages = root.get('pages', []) or []
    texts_by_page = [collect_text_blocks(p) for p in pages]
    top_texts = [t for page in texts_by_page for t in page[:6]][:20]
    section_titles = []
    for texts in texts_by_page[1:]:
        for t in texts[:3]:
            if len(t) <= 80:
                section_titles.append(t)
                break
    return {
        'sample_id': root.get('key') or path,
        'source_path': path,
        'name': root.get('name'),
        'category': root.get('category'),
        'format': infer_format(root),
        'page_count': len(pages),
        'canvas_layout_mode': root.get('canvas_layout_mode') or root.get('canvasLayoutMode'),
        'page_size': root.get('page_size'),
        'top_texts': top_texts,
        'section_titles': section_titles[:10],
        'color_palette': infer_color_palette(pages),
        'layout_traits': infer_layout_traits(root),
    }


def iter_input_paths(args: argparse.Namespace) -> Iterable[str]:
    seen = set()
    for p in args.input_path:
        if p not in seen:
            seen.add(p)
            yield p
    for prefix in args.input_prefix:
        for p in iter_json_paths(prefix):
            if p not in seen:
                seen.add(p)
                yield p


def load_processed_ids(path: str) -> set:
    done = set()
    if not path or not os.path.exists(path):
        return done
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            sid = obj.get('sample_id')
            if sid:
                done.add(sid)
    return done


async def call_llm(summary: Dict[str, Any], args: argparse.Namespace, key_pool: KeyPool) -> Dict[str, Any]:
    prompt = USER_TEMPLATE.format(schema_summary=json.dumps(summary, ensure_ascii=False, indent=2))
    messages = [{
        'role': 'user',
        'content': [{'type': 'text', 'text': prompt}],
    }]
    for attempt in range(3):
        api_key, limiter = await key_pool.acquire()
        await limiter.wait()
        try:
            resp = await asyncio.wait_for(
                async_chat_completion(
                    message=messages,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    api_key=api_key,
                    system_prompt=SYSTEM_PROMPT,
                    response_format={'type': 'json_object'},
                ),
                timeout=args.timeout_sec,
            )
            text = resp['choices'][0]['message']['content']
            if isinstance(text, list):
                text = ''.join(block.get('text', '') for block in text if isinstance(block, dict))
            return json.loads(text)
        except Exception as e:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError('unreachable')


async def worker(name: str, queue: asyncio.Queue, args: argparse.Namespace, key_pool: KeyPool, result_f, error_f):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        sample_id, path, summary = item
        try:
            llm_out = await call_llm(summary, args, key_pool)
            rec = {
                'sample_id': sample_id,
                'source_path': path,
                'schema_summary': summary,
                'reverse_query_result': llm_out,
                'error': None,
            }
            result_f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            result_f.flush()
        except Exception as e:
            err = {
                'sample_id': sample_id,
                'source_path': path,
                'schema_summary': summary,
                'error': repr(e),
            }
            error_f.write(json.dumps(err, ensure_ascii=False) + '\n')
            error_f.flush()
        finally:
            queue.task_done()


async def main_async():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    api_keys_raw = os.getenv(args.api_key_env, '').strip()
    if not api_keys_raw:
        raise ValueError(f'Missing API keys in env: {args.api_key_env}')
    api_keys = [x.strip() for x in api_keys_raw.split(',') if x.strip()]
    key_pool = KeyPool(api_keys, rpm=args.rpm)

    ts = time.strftime('%Y%m%d_%H%M%S')
    result_path = output_dir / f'result_reverse_query_{ts}.jsonl'
    error_path = output_dir / f'errors_reverse_query_{ts}.jsonl'
    stats_path = output_dir / f'stats_reverse_query_{ts}.json'

    processed = load_processed_ids(args.resume_result_file)
    queue = asyncio.Queue(maxsize=max(args.concurrency * 4, 32))

    scanned = 0
    parsed_ok = 0
    skipped_done = 0
    parse_failed = 0
    enqueued = 0

    with result_path.open('a', encoding='utf-8') as result_f, error_path.open('a', encoding='utf-8') as error_f:
        workers = [asyncio.create_task(worker(f'w{i}', queue, args, key_pool, result_f, error_f)) for i in range(args.concurrency)]

        for path in iter_input_paths(args):
            if args.limit and scanned >= args.limit:
                break
            scanned += 1
            try:
                with smart_open(path, 'r', encoding='utf-8') as f:
                    root = json.load(f)
                parsed_ok += 1
            except Exception:
                parse_failed += 1
                continue

            summary = summarize_schema(path, root)
            sample_id = summary['sample_id']
            if sample_id in processed:
                skipped_done += 1
                continue
            await queue.put((sample_id, path, summary))
            enqueued += 1

        for _ in workers:
            await queue.put(None)
        await queue.join()
        await asyncio.gather(*workers)

    with stats_path.open('w', encoding='utf-8') as f:
        json.dump({
            'scanned': scanned,
            'parsed_ok': parsed_ok,
            'parse_failed': parse_failed,
            'skipped_done': skipped_done,
            'enqueued': enqueued,
            'result_path': str(result_path),
            'error_path': str(error_path),
        }, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        'scanned': scanned,
        'parsed_ok': parsed_ok,
        'parse_failed': parse_failed,
        'skipped_done': skipped_done,
        'enqueued': enqueued,
        'result_path': str(result_path),
        'error_path': str(error_path),
        'stats_path': str(stats_path),
    }, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main_async())
