#!/usr/bin/env python3
"""
Youware 0423 reverse query generator
参考 /step3_data/code_agent_bmk/query_generation/generate_query_codepen_new.py 的调用方式，
但输入改为 youware_0423 的结构化样本，prompt 改为 0423 目录下的 v2 prompt。
"""
from __future__ import annotations

import os
import re
import json
import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path('/data/openclaw/youware_0423')
DEFAULT_INPUT = ROOT / 'inputs' / 'category15_input.json'
DEFAULT_OUTPUT = ROOT / 'outputs' / 'reference_style_runs'
PROMPT_MAP = {
    'game': ROOT / 'prompts' / '21_query_generation_game_v2.md',
    'dashboard': ROOT / 'prompts' / '22_query_generation_dashboard_v2.md',
    'ai-app': ROOT / 'prompts' / '23_query_generation_ai_app_v2.md',
    'education': ROOT / 'prompts' / '24_query_generation_education_v2.md',
    'landing-page': ROOT / 'prompts' / '25_query_generation_landing_page_v2.md',
    'presentation': ROOT / 'prompts' / '26_query_generation_presentation_v2.md',
    'productivity-tool': ROOT / 'prompts' / '27_query_generation_productivity_tool_v2.md',
}


def setup_logging(log_file: str) -> logging.Logger:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, encoding='utf-8')],
    )
    return logging.getLogger(__name__)


logger = setup_logging(str(ROOT / 'logs' / 'generate_query_0423.log'))


def import_async_chat_completion():
    import sys
    import_paths = ['step_align.model.proxy', 'step_align.proxy', 'proxy']
    for module_path in import_paths:
        try:
            module = __import__(module_path, fromlist=['async_chat_completion'])
            return getattr(module, 'async_chat_completion')
        except (ImportError, AttributeError):
            continue

    potential_paths = [
        Path('/data/step_align'),
        ROOT / 'step_align',
        ROOT.parent / 'cssdesignawards-query' / 'step_align',
    ]
    for p in potential_paths:
        if p.exists():
            sys.path.insert(0, str(p.parent if p.name == 'step_align' else p))
            for module_path in import_paths:
                try:
                    module = __import__(module_path, fromlist=['async_chat_completion'])
                    return getattr(module, 'async_chat_completion')
                except (ImportError, AttributeError):
                    continue
    raise ImportError('无法导入 async_chat_completion，请确认 step_align 模块可用')


async_chat_completion = import_async_chat_completion()


class AsyncRateLimiter:
    def __init__(self, rpm: int):
        self.capacity = max(1, rpm)
        self.tokens = float(self.capacity)
        self.refill_interval = 60.0
        self.last_refill_time = None
        self.lock = asyncio.Lock()

    async def acquire(self, permits: int = 1):
        while True:
            async with self.lock:
                now = asyncio.get_event_loop().time()
                if self.last_refill_time is None:
                    self.last_refill_time = now
                elapsed = now - self.last_refill_time
                if elapsed > 0:
                    refill = (elapsed / self.refill_interval) * self.capacity
                    self.tokens = min(self.capacity, self.tokens + refill)
                    self.last_refill_time = now
                if self.tokens >= permits:
                    self.tokens -= permits
                    return
            await asyncio.sleep(0.01)


class ConcurrencyController:
    def __init__(self, max_concurrent: int):
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def run_with_limit(self, coro):
        async with self.semaphore:
            return await coro


class QueryGenerator0423:
    def __init__(self, model: str, rpm: int, api_keys: List[str], max_output_tokens: int = 2200, temperature: float = 0.2):
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.api_keys = api_keys
        self.limiters = [AsyncRateLimiter(rpm) for _ in api_keys]
        self.current_key_index = 0

    def _pick_key(self):
        key_idx = self.current_key_index % len(self.api_keys)
        self.current_key_index += 1
        return self.api_keys[key_idx], self.limiters[key_idx]

    def _parse_json_response(self, content: str, index: int) -> Optional[Dict[str, Any]]:
        if not content:
            return None
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get('text')
                    if text is not None:
                        parts.append(str(text))
                elif part is not None:
                    parts.append(str(part))
            content = ''.join(parts)
        content = str(content).strip()
        try:
            obj = json.loads(content)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            try:
                obj = json.loads(json_match.group(1))
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                pass
        brace_match = re.search(r'\{[\s\S]*\}', content)
        if brace_match:
            try:
                obj = json.loads(brace_match.group(0))
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                pass
        logger.warning(f'样本 {index}: 无法解析JSON响应')
        return None

    async def _repair_json(self, bad_content: str, index: int) -> Optional[Dict[str, Any]]:
        api_key, limiter = self._pick_key()
        await limiter.acquire(1)
        system_prompt = '你必须只输出一个合法 JSON 对象，不要输出 markdown，不要输出解释，不要输出代码块。'
        user_prompt = '把下面内容整理成一个合法 JSON 对象，字段不要丢失，只输出 JSON。\n\n' + (bad_content or '')
        messages = [
            {'role': 'system', 'content': [{'type': 'text', 'text': system_prompt}]},
            {'role': 'user', 'content': [{'type': 'text', 'text': user_prompt}]},
        ]
        try:
            resp = await async_chat_completion(
                message=messages,
                model=self.model,
                max_tokens=self.max_output_tokens,
                temperature=0.0,
                top_p=1.0,
                n=1,
                api_key=api_key,
            )
            content = resp['choices'][0].get('message', {}).get('content', '') if resp.get('choices') else ''
            return self._parse_json_response(content, index)
        except Exception as e:
            logger.error(f'样本 {index}: repair调用失败 - {e}')
            return None

    async def generate_query(self, item: Dict[str, Any], prompt_text: str, index: int) -> Optional[Dict[str, Any]]:
        api_key, limiter = self._pick_key()
        await limiter.acquire(1)

        payload = {
            'id': item.get('id') or item.get('item_id'),
            'title': item.get('title', ''),
            'summary': item.get('summary', ''),
            'text': item.get('text', ''),
            'visible_text': item.get('visible_text', ''),
            'dom_summary': item.get('dom_summary', ''),
            'ocr_text': item.get('ocr_text', ''),
            'meta_description': item.get('meta_description', ''),
            'image_caption': item.get('image_caption', ''),
            'preset_category': item.get('preset_category', ''),
        }

        user_content = prompt_text.strip() + '\n\n输入样本：\n' + json.dumps(payload, ensure_ascii=False, indent=2)
        system_prompt = '你必须只输出一个合法 JSON 对象，不要输出 markdown，不要输出解释，不要输出代码块。'
        messages = [
            {'role': 'system', 'content': [{'type': 'text', 'text': system_prompt}]},
            {'role': 'user', 'content': [{'type': 'text', 'text': user_content}]},
        ]

        try:
            resp = await async_chat_completion(
                message=messages,
                model=self.model,
                max_tokens=self.max_output_tokens,
                temperature=self.temperature,
                top_p=1.0,
                n=1,
                api_key=api_key,
            )
            if isinstance(resp, dict) and resp.get('choices'):
                content = resp['choices'][0].get('message', {}).get('content', '') or ''
                parsed = self._parse_json_response(content, index)
                if parsed is None:
                    parsed = await self._repair_json(str(content), index)
                if parsed is None:
                    return None
                return {
                    'item': item,
                    'raw_output': content,
                    'parsed_output': parsed,
                }
            logger.warning(f'样本 {index}: API响应格式异常')
            return None
        except Exception as e:
            logger.error(f'样本 {index}: API调用失败 - {e}')
            return None


def load_items(input_path: Path) -> List[Dict[str, Any]]:
    data = json.loads(input_path.read_text(encoding='utf-8'))
    items = data['items'] if isinstance(data, dict) and 'items' in data else data
    if not isinstance(items, list):
        raise ValueError('input must be a list or an object with items[]')
    return items


def save_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


async def generate_queries(items: List[Dict[str, Any]], category: str, prompt_path: Path, model: str, rpm: int, api_keys: List[str], max_concurrent: int, output_dir: Path):
    prompt_text = prompt_path.read_text(encoding='utf-8')
    generator = QueryGenerator0423(model=model, rpm=rpm, api_keys=api_keys)
    concurrency = ConcurrencyController(max_concurrent)

    tasks = []
    for idx, item in enumerate(items, start=1):
        tasks.append(concurrency.run_with_limit(generator.generate_query(item, prompt_text, idx)))

    logger.info(f'开始生成 {category}，样本数={len(items)}')
    results = await asyncio.gather(*tasks)
    records = [x for x in results if x is not None]
    out_path = output_dir / f'{category}_{len(records)}_results.json'
    save_json(out_path, records)
    logger.info(f'{category} 完成，成功 {len(records)} 条，输出: {out_path}')
    return {
        'category': category,
        'count': len(records),
        'output_path': str(out_path),
        'ids': [r['item'].get('id') for r in records],
    }


async def main_async(args):
    items = load_items(Path(args.input))
    api_key = os.getenv('STEP_ALIGN_API_KEY') or os.getenv('API_KEY') or os.getenv('OPENAI_API_KEY') or os.getenv('MODEL_PROXY_TOKEN')
    if not api_key:
        raise RuntimeError('未找到可用 API key')
    api_keys = [x for x in [api_key] if x]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {'runs': []}
    for category in args.categories:
        if category not in PROMPT_MAP:
            raise ValueError(f'unsupported category: {category}')
        selected = [x for x in items if x.get('preset_category') == category][:args.limit]
        summary['runs'].append(
            await generate_queries(
                items=selected,
                category=category,
                prompt_path=PROMPT_MAP[category],
                model=args.model,
                rpm=args.rpm,
                api_keys=api_keys,
                max_concurrent=args.max_concurrent,
                output_dir=output_dir,
            )
        )

    save_json(output_dir / 'run_summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description='Generate reverse queries using youware_0423 prompts')
    parser.add_argument('--input', default=str(DEFAULT_INPUT))
    parser.add_argument('--output-dir', default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        '--categories',
        nargs='+',
        default=['game', 'dashboard', 'ai-app', 'education', 'landing-page', 'presentation', 'productivity-tool'],
    )
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--model', default='gemini-3-pro-thinking')
    parser.add_argument('--rpm', type=int, default=30)
    parser.add_argument('--max-output-tokens', type=int, default=2200)
    parser.add_argument('--max-concurrent', type=int, default=3)
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    asyncio.run(main_async(args))
