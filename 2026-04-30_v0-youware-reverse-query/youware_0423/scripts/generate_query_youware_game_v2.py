#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from megfile import smart_open, smart_walk

DEFAULT_PROMPT_PATH = Path('/data/openclaw/youware_0423/prompts/21_query_generation_game_v2.md')
DEFAULT_S3_BASE = 's3://collect-data-text/202511/h5sites_resource/youware/game'
DEFAULT_OUT_DIR = Path('/data/openclaw/youware_0423/outputs/query_generation_game_v2')


def import_async_chat_completion():
    import sys
    from pathlib import Path as _Path

    import_paths = ['step_align.model.proxy', 'step_align.proxy', 'proxy']
    for module_path in import_paths:
        try:
            module = __import__(module_path, fromlist=['async_chat_completion'])
            return getattr(module, 'async_chat_completion')
        except (ImportError, AttributeError):
            continue

    potential_paths = [
        _Path('/data/step_align'),
        _Path(__file__).resolve().parent / 'step_align',
        _Path(__file__).resolve().parent.parent / 'step_align',
        _Path(__file__).resolve().parent.parent.parent / 'step_align',
    ]
    for p in potential_paths:
        if not p.exists():
            continue
        sys.path.insert(0, str(p.parent if p.name == 'step_align' else p))
        for module_path in import_paths:
            try:
                module = __import__(module_path, fromlist=['async_chat_completion'])
                return getattr(module, 'async_chat_completion')
            except (ImportError, AttributeError):
                continue

    raise ImportError('无法导入 async_chat_completion')


async_chat_completion = import_async_chat_completion()


def ts() -> str:
    now = time.localtime()
    return f'{now.tm_mon:02d}-{now.tm_mday:02d} {now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}'


def log(msg: str) -> None:
    print(f'[{ts()}] {msg}', flush=True)


def normalize_s3_uri(uri: str) -> str:
    u = (uri or '').strip()
    if u.startswith('s3://s3://'):
        u = 's3://' + u[len('s3://s3://') :]
    return u.rstrip('/')


def safe_read_json(path: str) -> Optional[Any]:
    try:
        with smart_open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def safe_read_text(path: str, max_chars: int) -> str:
    try:
        with smart_open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        if max_chars > 0 and len(text) > max_chars:
            return text[:max_chars]
        return text
    except Exception:
        return ''


def html_extract_title(html: str) -> str:
    m = re.search(r'<title[^>]*>([\s\S]*?)</title>', html, flags=re.IGNORECASE)
    return unescape(m.group(1).strip()) if m else ''


def html_extract_meta_description(html: str) -> str:
    m = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([\s\S]*?)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([\s\S]*?)["\'][^>]*name=["\']description["\']',
            html,
            flags=re.IGNORECASE,
        )
    return unescape(m.group(1).strip()) if m else ''


def html_extract_visible_text(html: str, max_chars: int) -> str:
    txt = re.sub(r'<script[\s\S]*?</script>', ' ', html, flags=re.IGNORECASE)
    txt = re.sub(r'<style[\s\S]*?</style>', ' ', txt, flags=re.IGNORECASE)
    txt = re.sub(r'<noscript[\s\S]*?</noscript>', ' ', txt, flags=re.IGNORECASE)
    txt = re.sub(r'<[^>]+>', ' ', txt)
    txt = unescape(txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt[:max_chars] if max_chars > 0 else txt


def html_dom_summary(html: str) -> Dict[str, Any]:
    lower = html.lower()
    return {
        'contains_canvas': '<canvas' in lower,
        'tag_counts': {
            'canvas': len(re.findall(r'<canvas\b', lower)),
            'button': len(re.findall(r'<button\b', lower)),
            'audio': len(re.findall(r'<audio\b', lower)),
            'video': len(re.findall(r'<video\b', lower)),
            'svg': len(re.findall(r'<svg\b', lower)),
            'img': len(re.findall(r'<img\b', lower)),
        },
    }


def collect_index_json_paths(s3_base: str) -> List[str]:
    paths: List[str] = []
    for root, _dirs, files in smart_walk(s3_base):
        if 'index.json' in files:
            paths.append(root.rstrip('/') + '/index.json')
    paths.sort()
    return paths


def summarize_resource_map(resource_map: Any) -> Dict[str, Any]:
    if not isinstance(resource_map, dict):
        return {'total': 0, 'js': [], 'css': [], 'images': [], 'fonts': [], 'other_count': 0}

    values = [str(v) for v in resource_map.values()]
    js = [v for v in values if v.endswith('.js')]
    css = [v for v in values if v.endswith('.css')]
    images = [v for v in values if re.search(r'\.(png|jpg|jpeg|gif|webp|svg)$', v, flags=re.IGNORECASE)]
    fonts = [v for v in values if re.search(r'\.(woff|woff2|ttf|otf)$', v, flags=re.IGNORECASE)]
    known = set(js + css + images + fonts)
    other_count = len([v for v in values if v not in known])
    return {
        'total': len(values),
        'js': js[:30],
        'css': css[:30],
        'images': images[:50],
        'fonts': fonts[:30],
        'other_count': other_count,
    }


def project_slug_from_index_path(index_json_path: str) -> str:
    # s3://.../game/<slug>/index.json -> <slug>
    chunks = index_json_path.rstrip('/').split('/')
    if len(chunks) >= 2:
        return chunks[-2]
    return ''


def build_input_payload(
    index_json_path: str,
    html_chars: int,
    visible_text_chars: int,
    js_files_limit: int,
    js_chars_each: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    project_root = index_json_path.rsplit('/', 1)[0]
    slug = project_slug_from_index_path(index_json_path)
    index_html_path = project_root + '/index.html'
    resource_map_path = project_root + '/resource_map.json'

    index_json = safe_read_json(index_json_path)
    resource_map = safe_read_json(resource_map_path)
    index_html = safe_read_text(index_html_path, html_chars)

    html_title = html_extract_title(index_html) if index_html else ''
    meta_description = html_extract_meta_description(index_html) if index_html else ''
    visible_text = html_extract_visible_text(index_html, visible_text_chars) if index_html else ''
    dom_summary = html_dom_summary(index_html) if index_html else {}
    resource_summary = summarize_resource_map(resource_map)

    js_snippets: List[Dict[str, Any]] = []
    for rel in resource_summary.get('js', [])[: max(js_files_limit, 0)]:
        js_path = project_root + '/' + rel.lstrip('/')
        snippet = safe_read_text(js_path, js_chars_each)
        js_snippets.append(
            {
                'path': js_path,
                'head_snippet': snippet,
                'snippet_chars': len(snippet),
            }
        )

    title = ''
    summary = ''
    category = ''
    site_url = ''
    project_url = ''
    if isinstance(index_json, dict):
        title = str(index_json.get('title') or '')
        summary = str(index_json.get('description') or '')
        category = str(index_json.get('category') or '')
        site_url = str(index_json.get('site_url') or '')
        project_url = str(index_json.get('project_url') or '')

    payload = {
        'id': slug,
        'title': title or html_title,
        'summary': summary or meta_description,
        'text': visible_text,
        'visible_text': visible_text,
        'dom_summary': dom_summary,
        'ocr_text': '',
        'meta_description': meta_description,
        'image_caption': '',
        'preset_category': 'game' if (category.lower() == 'game') else category,
        'source_paths': {
            'project_root': project_root,
            'index_json': index_json_path,
            'index_html': index_html_path,
            'resource_map': resource_map_path,
        },
        'code_evidence': {
            'resource_summary': resource_summary,
            'js_snippets': js_snippets,
            'index_json': index_json,
        },
    }
    sample_meta = {
        'slug': slug,
        'title': payload.get('title', ''),
        'project_root': project_root,
        'index_json_path': index_json_path,
        'site_url': site_url,
        'project_url': project_url,
    }
    return payload, sample_meta


def extract_choice_text(resp: Any) -> str:
    if not isinstance(resp, dict):
        return ''
    choices = resp.get('choices')
    if not isinstance(choices, list) or not choices:
        return ''
    first = choices[0]
    if not isinstance(first, dict):
        return ''
    msg = first.get('message')
    if isinstance(msg, dict):
        content = msg.get('content', '')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: List[str] = []
            for part in content:
                if isinstance(part, str):
                    chunks.append(part)
                elif isinstance(part, dict):
                    t = part.get('text')
                    if isinstance(t, str):
                        chunks.append(t)
            return ''.join(chunks)
    txt = first.get('text')
    if isinstance(txt, str):
        return txt
    return ''


def parse_json_object(text: str) -> Dict[str, Any]:
    raw = (text or '').strip()
    if not raw:
        raise ValueError('empty model response')

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    for m in re.finditer(r'```(?:json)?\s*([\s\S]*?)\s*```', raw, flags=re.IGNORECASE):
        frag = m.group(1).strip()
        if not frag:
            continue
        try:
            obj = json.loads(frag)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    left = raw.find('{')
    right = raw.rfind('}')
    if left != -1 and right != -1 and right > left:
        frag = raw[left : right + 1]
        obj = json.loads(frag)
        if isinstance(obj, dict):
            return obj

    raise ValueError('no valid JSON object found')


def load_done_map(out_jsonl: Path) -> Dict[str, Dict[str, Any]]:
    done: Dict[str, Dict[str, Any]] = {}
    if not out_jsonl.exists():
        return done
    with out_jsonl.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            index_path = obj.get('sample_meta', {}).get('index_json_path')
            if isinstance(index_path, str) and index_path:
                done[index_path] = obj
    return done


@dataclass
class RateLimiter:
    rpm: int

    def __post_init__(self):
        self.min_interval = 60.0 / max(self.rpm, 1)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = time.time()
            delta = now - self._last
            if delta < self.min_interval:
                await asyncio.sleep(self.min_interval - delta)
            self._last = time.time()


class KeyPool:
    def __init__(self, keys: List[str]):
        self.keys = keys
        self.idx = 0
        self.lock = asyncio.Lock()

    async def next_key(self) -> str:
        async with self.lock:
            key = self.keys[self.idx % len(self.keys)]
            self.idx += 1
            return key


def resolve_api_keys(cli_keys: Optional[List[str]]) -> List[str]:
    keys = [k for k in (cli_keys or []) if k]
    if keys:
        return keys
    for env_name in ['API_KEY', 'OPENAI_API_KEY', 'STEP_ALIGN_API_KEY', 'MODEL_PROXY_TOKEN', 'LLM_API_KEY']:
        v = os.getenv(env_name)
        if v:
            return [v]
    return []


async def generate_one(
    model: str,
    prompt_text: str,
    payload: Dict[str, Any],
    key_pool: KeyPool,
    limiter: RateLimiter,
    max_tokens: int,
    temperature: float,
    top_p: float,
    timeout_sec: int,
    response_format_json: bool,
) -> Tuple[Dict[str, Any], str]:
    system_prompt = (
        '你必须只输出一个合法 JSON 对象，不要输出 markdown，不要输出解释，不要输出代码块。'
        '严格按照用户给定规则填写字段。'
    )
    user_prompt = prompt_text.strip() + '\n\n输入样本：\n' + json.dumps(payload, ensure_ascii=False, indent=2)
    messages = [
        {'role': 'system', 'content': [{'type': 'text', 'text': system_prompt}]},
        {'role': 'user', 'content': [{'type': 'text', 'text': user_prompt}]},
    ]

    last_err: Optional[Exception] = None
    for attempt in range(3):
        api_key = await key_pool.next_key()
        try:
            await limiter.wait()
            kwargs: Dict[str, Any] = {
                'message': messages,
                'model': model,
                'max_tokens': max_tokens,
                'temperature': temperature,
                'top_p': top_p,
                'n': 1,
                'api_key': api_key,
            }
            if response_format_json:
                kwargs['response_format'] = {'type': 'json_object'}

            resp = await asyncio.wait_for(async_chat_completion(**kwargs), timeout=timeout_sec)
            text = extract_choice_text(resp)
            parsed = parse_json_object(text)
            return parsed, text
        except Exception as e:
            last_err = e
            await asyncio.sleep((2 ** attempt) + random.random())

    raise RuntimeError(f'model call failed after retries: {repr(last_err)}')


async def worker(
    worker_id: int,
    queue: asyncio.Queue,
    prompt_text: str,
    args: argparse.Namespace,
    key_pool: Optional[KeyPool],
    limiter: Optional[RateLimiter],
    out_jsonl: Path,
    done_map: Dict[str, Dict[str, Any]],
    write_lock: asyncio.Lock,
    stats: Dict[str, int],
    start_time: float,
) -> None:
    while True:
        index_json_path = await queue.get()
        if index_json_path is None:
            queue.task_done()
            return

        try:
            payload, sample_meta = await asyncio.to_thread(
                build_input_payload,
                index_json_path,
                args.html_chars,
                args.visible_text_chars,
                args.js_files_limit,
                args.js_chars_each,
            )

            if args.dry_run:
                generated = {
                    'product_query': '',
                    'feature_query': '',
                    'is_complete': False,
                    'reason': 'dry_run mode: skip LLM call',
                    'category1': '',
                    'category2': '',
                    'category_is_game': True,
                    'category_decision_reason': 'dry_run mode',
                    'queries': [],
                }
                raw_text = ''
            else:
                if key_pool is None or limiter is None:
                    raise RuntimeError('key pool / limiter missing while dry_run is False')
                generated, raw_text = await generate_one(
                    model=args.model,
                    prompt_text=prompt_text,
                    payload=payload,
                    key_pool=key_pool,
                    limiter=limiter,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    timeout_sec=args.timeout_sec,
                    response_format_json=args.response_format_json,
                )

            out_obj: Dict[str, Any] = {
                'sample_meta': sample_meta,
                'generated_query': generated,
                'model': args.model,
                'prompt_path': str(args.prompt_path),
            }
            if args.save_raw_output:
                out_obj['raw_response'] = raw_text
            if args.save_input_payload:
                out_obj['input_payload'] = payload
            ok = True
        except Exception as e:
            out_obj = {
                'sample_meta': {
                    'index_json_path': index_json_path,
                    'slug': project_slug_from_index_path(index_json_path),
                },
                'error': str(e),
                'model': args.model,
                'prompt_path': str(args.prompt_path),
            }
            ok = False

        async with write_lock:
            with out_jsonl.open('a', encoding='utf-8') as f:
                f.write(json.dumps(out_obj, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())
            done_map[index_json_path] = out_obj

            stats['done'] += 1
            if ok:
                stats['success'] += 1
            else:
                stats['failed'] += 1

            elapsed = time.time() - start_time
            pct = (stats['done'] / stats['total'] * 100.0) if stats['total'] else 100.0
            log(
                f'[worker={worker_id}] done={stats["done"]}/{stats["total"]} ({pct:.2f}%) '
                f'success={stats["success"]} failed={stats["failed"]} elapsed={elapsed:.1f}s '
                f'slug={out_obj.get("sample_meta", {}).get("slug", "")}'
            )

            if args.checkpoint_every > 0 and stats['done'] % args.checkpoint_every == 0:
                ckpt_path = args.out_dir / f'{args.run_name}.checkpoint_{stats["done"]}.json'
                ckpt_path.write_text(
                    json.dumps(list(done_map.values()), ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                log(f'[checkpoint] saved={ckpt_path}')
        queue.task_done()


async def amain(args: argparse.Namespace) -> None:
    args.s3_base = normalize_s3_uri(args.s3_base)
    args.prompt_path = Path(args.prompt_path)
    args.out_dir = Path(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if not args.prompt_path.exists():
        raise FileNotFoundError(f'prompt file not found: {args.prompt_path}')

    out_jsonl = args.out_dir / f'{args.run_name}.jsonl'
    out_json = args.out_dir / f'{args.run_name}.json'

    if args.overwrite:
        if out_jsonl.exists():
            out_jsonl.unlink()
        if out_json.exists():
            out_json.unlink()

    done_map = load_done_map(out_jsonl)

    all_index_paths = await asyncio.to_thread(collect_index_json_paths, args.s3_base)
    if args.offset > 0:
        all_index_paths = all_index_paths[args.offset :]
    if args.limit is not None:
        all_index_paths = all_index_paths[: args.limit]

    pending = [p for p in all_index_paths if p not in done_map]
    prompt_text = args.prompt_path.read_text(encoding='utf-8')

    key_pool: Optional[KeyPool] = None
    limiter: Optional[RateLimiter] = None
    if not args.dry_run:
        keys = resolve_api_keys(args.api_keys)
        if not keys:
            raise RuntimeError('missing API key: use --api_keys or env API_KEY/OPENAI_API_KEY/STEP_ALIGN_API_KEY')
        key_pool = KeyPool(keys)
        limiter = RateLimiter(args.rpm)

    stats = {
        'total': len(all_index_paths),
        'done': len(done_map),
        'success': len(done_map),
        'failed': 0,
    }
    start_time = time.time()

    log(
        f'[start] total={len(all_index_paths)} done_existing={len(done_map)} pending={len(pending)} '
        f'model={args.model} concurrency={args.concurrency} rpm={args.rpm} '
        f'dry_run={args.dry_run} s3_base={args.s3_base}'
    )

    queue: asyncio.Queue = asyncio.Queue()
    for p in pending:
        await queue.put(p)
    for _ in range(args.concurrency):
        await queue.put(None)

    write_lock = asyncio.Lock()
    workers = [
        asyncio.create_task(
            worker(
                worker_id=i + 1,
                queue=queue,
                prompt_text=prompt_text,
                args=args,
                key_pool=key_pool,
                limiter=limiter,
                out_jsonl=out_jsonl,
                done_map=done_map,
                write_lock=write_lock,
                stats=stats,
                start_time=start_time,
            )
        )
        for i in range(args.concurrency)
    ]

    await queue.join()
    await asyncio.gather(*workers)

    out_json.write_text(json.dumps(list(done_map.values()), ensure_ascii=False, indent=2), encoding='utf-8')
    log(
        f'[done] records={len(done_map)} success={stats["success"]} failed={stats["failed"]} '
        f'jsonl={out_jsonl} json={out_json}'
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description='Generate high-density reverse queries from youware game S3 projects using game prompt v2.'
    )
    ap.add_argument('--s3_base', default=DEFAULT_S3_BASE)
    ap.add_argument('--prompt_path', default=str(DEFAULT_PROMPT_PATH))
    ap.add_argument('--out_dir', default=str(DEFAULT_OUT_DIR))
    ap.add_argument('--run_name', default='game_query_generation_v2')

    ap.add_argument('--model', default='gemini-3-pro-thinking')
    ap.add_argument('--api_keys', nargs='*', default=None)
    ap.add_argument('--temperature', type=float, default=0.2)
    ap.add_argument('--top_p', type=float, default=1.0)
    ap.add_argument('--max_tokens', type=int, default=3500)
    ap.add_argument('--timeout_sec', type=int, default=180)
    ap.add_argument('--response_format_json', action='store_true')

    ap.add_argument('--concurrency', type=int, default=10)
    ap.add_argument('--rpm', type=int, default=120)
    ap.add_argument('--checkpoint_every', type=int, default=500)

    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--overwrite', action='store_true')
    ap.add_argument('--dry_run', action='store_true')

    ap.add_argument('--html_chars', type=int, default=30000)
    ap.add_argument('--visible_text_chars', type=int, default=5000)
    ap.add_argument('--js_files_limit', type=int, default=2)
    ap.add_argument('--js_chars_each', type=int, default=12000)

    ap.add_argument('--save_raw_output', action='store_true')
    ap.add_argument('--save_input_payload', action='store_true')
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(amain(args))


if __name__ == '__main__':
    main()
