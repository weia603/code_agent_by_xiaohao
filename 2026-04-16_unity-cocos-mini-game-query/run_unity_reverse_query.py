#!/usr/bin/env python3
"""
Batch-generate reverse product requirements from Unity project archive summaries.
Goal: describe the final product shape only, not implementation details.
Streaming + checkpointed JSONL output.
"""

import argparse
import asyncio
import ast
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

try:
    from step_align.model.proxy import async_chat_completion
except Exception:
    async_chat_completion = None

SYSTEM_PROMPT_UNITY = """# Role & Objective
你是一个资深游戏产品经理。你的任务不是解释源码如何实现，而是根据项目压缩包中暴露出的玩法、界面、系统、资源、音效、场景等信号，逆向还原出“这个项目最终运行起来像什么产品”的原始产品需求描述。

你的输出必须像产品经理在项目最早期写下的需求文档，而不是技术方案，不是工程结构总结，也不是逆向分析报告。

# Core Principles
1. 只描述最终产品体验，不描述技术实现。
2. 严禁在 query 中出现 Unity、Cocos、Laya、引擎、源码、压缩包、目录结构、文件名、脚本名等词。
3. 即使一个包更像模板、starter kit、framework、toolkit、asset pack、素材包，或者信息不足，也仍然要尽量生成一版“这个项目最终运行起来可能是什么产品”的 query；只是这版 query 可以更保守、更泛化。
4. 不允许因为信息不足就直接不给 query；必须先生成 query，再判断这版 query 是否足够完整且好。
5. 如果信息足够，优先还原：
   - 产品类型
   - 用户操作方式
   - 核心玩法循环
   - 关卡目标/胜负条件
   - 系统与数值
   - 交互与界面
   - 视听表现

# Output Rules
输出必须是合法 JSON 对象，只能包含以下字段：
{
  "suitability": "high | medium | low | fail",
  "reasoning": "string",
  "semantic_brief": {
    "summary": "string"
  },
  "is_complete_and_good_mini_game_requirement": true,
  "query": "string",
  "query_en": "string",
  "negative_constraints": ["string"]
}

# Query Writing Style
query 必须写成“原始产品需求描述”，建议自然组织成：
- 核心玩法循环
- 系统与数值
- 交互与界面
- 视听表现

但不要写任何技术栈要求。

# Mandatory Output Rule
无论样本质量高低，都必须输出 query 和 query_en。
- `is_complete_and_good_mini_game_requirement=true`：表示这版 query 已经足够完整、质量较高，像一个完整且好的小游戏产品需求。
- `is_complete_and_good_mini_game_requirement=false`：表示虽然已经生成了一版 query，但它更保守、更泛化，或者不够完整、不够稳定，还不能算一个完整且好的小游戏产品需求。
- 只有在模型完全没有返回合法 JSON 时，才允许走程序侧兜底。
"""


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


def load_config(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def resolve_api_keys(raw_keys: List[str]) -> List[str]:
    out = []
    for item in raw_keys:
        if item.startswith('ENV:'):
            v = os.getenv(item[4:])
            if v:
                out.append(v)
        elif item:
            out.append(item)
    if not out:
        raise ValueError('No usable API keys found')
    return out


def ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)


def load_processed_ids(result_file: str) -> set:
    done = set()
    if not os.path.exists(result_file):
        return done
    with open(result_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                sid = obj.get('sample_id')
                if sid:
                    done.add(sid)
            except Exception:
                continue
    return done


def iter_input_rows(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict):
                t = item.get('text')
                if isinstance(t, str):
                    chunks.append(t)
        return ''.join(chunks)
    if isinstance(content, dict):
        t = content.get('text')
        if isinstance(t, str):
            return t
    return ''


def extract_choice_text(choice: Any) -> str:
    if not isinstance(choice, dict):
        return ''
    msg = choice.get('message')
    if isinstance(msg, dict):
        txt = extract_message_text(msg.get('content', ''))
        if txt:
            return txt
    txt = choice.get('text')
    if isinstance(txt, str):
        return txt
    return ''


def parse_model_json(text: str) -> Dict[str, Any]:
    raw = (text or '').strip()
    if not raw:
        raise ValueError('empty model response')
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE):
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
        frag = raw[left:right + 1]
        try:
            obj = json.loads(frag)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        try:
            obj = ast.literal_eval(frag)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    raise ValueError('model output is not a valid JSON object')


def make_fail(sample: Dict[str, Any], reason: str) -> Dict[str, Any]:
    topic = sample.get('file_name', '') or sample.get('sample_id', '')
    summary = sample.get('archive_summary', {}) if isinstance(sample.get('archive_summary'), dict) else {}
    product_hints = summary.get('product_hints') or []
    ui_hints = summary.get('ui_hints') or []
    system_hints = summary.get('system_hints') or []
    feedback_hints = summary.get('feedback_hints') or []
    top_dirs = summary.get('top_level_dirs') or []

    cue_parts = []
    for arr in [product_hints[:3], ui_hints[:2], system_hints[:2], feedback_hints[:2], top_dirs[:2]]:
        for x in arr:
            if isinstance(x, str) and x.strip():
                cue_parts.append(x.strip())
    cue_text = '；'.join(cue_parts[:8]) if cue_parts else topic

    fallback_query = (
        f"请基于当前项目中可见的线索，设计一版低置信度但尽量具体的小游戏产品需求。已知线索包括：{cue_text}。"
        "请围绕这些线索，推测该产品最终运行后的核心玩法、用户目标、基础界面流程、胜负条件，以及最基本的反馈表现；"
        "如果信息不足，可以让方案更轻、更泛，但仍需尽量贴合这些已有线索，而不是输出通用模板。"
    )
    return {
        'suitability': 'fail',
        'reasoning': reason,
        'semantic_brief': {'summary': f'Low-confidence product description inferred for {topic}'.strip()},
        'is_complete_and_good_mini_game_requirement': False,
        'query': fallback_query,
        'query_en': fallback_query,
        'negative_constraints': [
            'Do not fabricate gameplay beyond available clues',
            'Do not expose source-code or archive-analysis traces',
            'Keep the query specific to the observed hints instead of using a generic template'
        ]
    }


def normalize_output(sample: Dict[str, Any], raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    query = raw.get('query') if isinstance(raw.get('query'), str) else ''
    query_en = raw.get('query_en') if isinstance(raw.get('query_en'), str) else ''
    if not query:
        return make_fail(sample, 'Model failed to produce a usable product requirement description')
    if not query_en:
        query_en = query
    suitability = raw.get('suitability') or 'high'
    reasoning = raw.get('reasoning') or 'Inferred from scenes, UI flow, system signals, gameplay hints, and feedback resources.'
    semantic_brief = raw.get('semantic_brief') if isinstance(raw.get('semantic_brief'), dict) else {'summary': sample.get('file_name', '')}
    if 'summary' not in semantic_brief:
        semantic_brief = {'summary': sample.get('file_name', '')}
    is_good = raw.get('is_complete_and_good_mini_game_requirement')
    if not isinstance(is_good, bool):
        is_good = suitability in ('high', 'medium')
    negative_constraints = raw.get('negative_constraints')
    if not isinstance(negative_constraints, list):
        negative_constraints = [
            'Do not mention engines or code structure',
            'Do not expose archive-analysis traces',
            'Do not invent missing gameplay systems'
        ]
    return {
        'suitability': suitability,
        'reasoning': reasoning,
        'semantic_brief': {'summary': str(semantic_brief.get('summary', '')).strip()},
        'is_complete_and_good_mini_game_requirement': is_good,
        'query': query,
        'query_en': query_en,
        'negative_constraints': negative_constraints,
    }


async def call_llm(sample: Dict[str, Any], cfg: Dict[str, Any], key_pool: KeyPool, limiter: RateLimiter):
    if async_chat_completion is None:
        raise RuntimeError('step_align.model.proxy.async_chat_completion import failed')
    messages = [
        {'role': 'system', 'content': [{'type': 'text', 'text': SYSTEM_PROMPT_UNITY}]},
        {'role': 'user', 'content': [{'type': 'text', 'text': json.dumps(sample, ensure_ascii=False, indent=2)}]}
    ]
    last_err = None
    last_text = ''
    for attempt in range(3):
        api_key = await key_pool.next_key()
        try:
            await limiter.wait()
            req_kwargs: Dict[str, Any] = dict(
                message=messages,
                model=cfg['llm']['model'],
                max_tokens=cfg['llm'].get('max_tokens', 4096),
                temperature=cfg['llm'].get('temperature', 0.2),
                api_key=api_key,
            )
            if cfg['llm'].get('enable_response_format', True):
                req_kwargs['response_format'] = {'type': 'json_object'}
            resp = await asyncio.wait_for(async_chat_completion(**req_kwargs), timeout=cfg['llm'].get('timeout_sec', 180))
            choices = resp.get('choices', []) if isinstance(resp, dict) else []
            first_choice = choices[0] if choices else {}
            text = extract_choice_text(first_choice)
            last_text = text
            parsed = parse_model_json(text)
            normalized = normalize_output(sample, parsed)
            return {'normalized': normalized, 'raw_text': text, 'raw_parsed': parsed}
        except Exception as e:
            last_err = e
            await asyncio.sleep((2 ** attempt) + random.random())
    fail_obj = make_fail(sample, f'Model call failed after retries: {repr(last_err)}')
    return {'normalized': fail_obj, 'raw_text': last_text, 'raw_parsed': None}


async def process_one(row: Dict[str, Any], cfg: Dict[str, Any], key_pool: KeyPool, limiter: RateLimiter, sem: asyncio.Semaphore, result_file: str, error_file: str):
    async with sem:
        llm_resp = await call_llm(row, cfg, key_pool, limiter)
        llm_out = llm_resp.get('normalized', {})
        out = {
            'sample_id': row.get('sample_id'),
            'source_path': row.get('source_path'),
            'file_name': row.get('file_name'),
            'source_type': row.get('source_type'),
            'reverse_query_result': llm_out,
            'raw_model_response': llm_resp.get('raw_text', ''),
            'raw_parsed_response': llm_resp.get('raw_parsed'),
        }
        with open(result_file, 'a', encoding='utf-8') as w:
            w.write(json.dumps(out, ensure_ascii=False) + '\n')
            w.flush()
        if llm_out.get('suitability') == 'fail':
            err = {
                'sample_id': row.get('sample_id'),
                'source_path': row.get('source_path'),
                'file_name': row.get('file_name'),
                'error': llm_out.get('reasoning', 'Unknown fail reason'),
            }
            with open(error_file, 'a', encoding='utf-8') as w:
                w.write(json.dumps(err, ensure_ascii=False) + '\n')
                w.flush()


async def amain(args):
    cfg = load_config(args.config)
    ensure_dir(args.output_dir)
    result_file = os.path.join(args.output_dir, 'result_game_reverse_query.jsonl')
    error_file = os.path.join(args.output_dir, 'errors_game_reverse_query.jsonl')
    done = load_processed_ids(result_file)
    api_keys = resolve_api_keys(cfg['llm']['api_keys'])
    key_pool = KeyPool(api_keys)
    limiter = RateLimiter(cfg['llm'].get('rpm', 60))
    sem = asyncio.Semaphore(cfg['llm'].get('concurrency', 3))
    batch_size = cfg['runtime'].get('batch_size', 3)
    tasks = []
    submitted = 0
    for row in iter_input_rows(args.input_jsonl):
        sid = row.get('sample_id')
        if sid in done:
            continue
        tasks.append(asyncio.create_task(process_one(row, cfg, key_pool, limiter, sem, result_file, error_file)))
        submitted += 1
        if len(tasks) >= batch_size:
            await asyncio.gather(*tasks)
            tasks = []
            print(f'submitted={submitted}', file=sys.stderr)
    if tasks:
        await asyncio.gather(*tasks)
        print(f'submitted={submitted}', file=sys.stderr)
    print(json.dumps({'result_file': result_file, 'error_file': error_file, 'submitted': submitted}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--input-jsonl', required=True)
    ap.add_argument('--output-dir', required=True)
    args = ap.parse_args()
    asyncio.run(amain(args))


if __name__ == '__main__':
    main()
