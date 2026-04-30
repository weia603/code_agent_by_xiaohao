#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path('/data/openclaw/youware_0423')
SOURCE_ROOT = Path('/data/openclaw/youware')
SCRIPTS = SOURCE_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from common.llm_bridge import create_bridge  # type: ignore

PROMPT_MAP = {
    'game': ROOT / 'prompts' / '21_query_generation_game_v2.md',
    'dashboard': ROOT / 'prompts' / '22_query_generation_dashboard_v2.md',
}


def load_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding='utf-8'))
    items = data['items'] if isinstance(data, dict) and 'items' in data else data
    if not isinstance(items, list):
        raise ValueError('input must be a list or an object with items[]')
    return items


def json_only_system_prompt() -> str:
    return (
        '你必须只输出一个合法 JSON 对象，不要输出 markdown，不要输出解释，不要输出代码块。'
        'JSON 中不要缺字段，字符串字段必须是字符串，布尔字段必须是 true/false，数组字段必须是数组。'
    )


def build_user_prompt(prompt_text: str, item: dict[str, Any]) -> str:
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
    return prompt_text.strip() + '\n\n输入样本：\n' + json.dumps(payload, ensure_ascii=False, indent=2)


def extract_json_object(text: str) -> dict[str, Any]:
    text = (text or '').strip()
    if not text:
        raise ValueError('empty model output')
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        obj = json.loads(text[start:end + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError('no valid JSON object found')


def call_provider(bridge: Any, system_prompt: str, user_prompt: str, max_tokens: int = 1800, temperature: float = 0.2) -> str:
    provider = getattr(bridge, 'provider', None)
    if provider is None:
        raise RuntimeError('no provider available')

    if provider.__class__.__name__ == 'StepAlignProxyProvider':
        messages = [
            {'role': 'system', 'content': [{'type': 'text', 'text': system_prompt}]},
            {'role': 'user', 'content': [{'type': 'text', 'text': user_prompt}]},
        ]
        response = provider._run_async(provider._call(messages=messages, max_tokens=max_tokens, temperature=temperature))
        return provider._extract_content(response)

    body = {
        'model': provider.model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    result = provider._request(body, expect_json=False)
    return result.get('content', '')


def repair_with_second_call(bridge: Any, raw_text: str) -> str:
    repair_system = json_only_system_prompt()
    repair_user = (
        '把下面这段模型输出整理成一个合法 JSON 对象。'
        '不要补充额外解释，不要输出 markdown，只返回 JSON 对象。\n\n原始输出：\n' + raw_text
    )
    return call_provider(bridge, repair_system, repair_user, max_tokens=1800, temperature=0.0)


def run_category(items: list[dict[str, Any]], category: str, limit: int, out_dir: Path) -> dict[str, Any]:
    prompt_path = PROMPT_MAP[category]
    prompt_text = prompt_path.read_text(encoding='utf-8')
    bridge = create_bridge('auto')
    selected = [x for x in items if x.get('preset_category') == category][:limit]
    results = []
    raw_dir = out_dir / 'raw'
    raw_dir.mkdir(parents=True, exist_ok=True)

    for item in selected:
        item_id = str(item.get('id') or item.get('item_id') or 'unknown')
        system_prompt = json_only_system_prompt()
        user_prompt = build_user_prompt(prompt_text, item)
        raw = call_provider(bridge, system_prompt, user_prompt)
        (raw_dir / f'{category}_{item_id}.txt').write_text(raw or '', encoding='utf-8')

        repaired_raw = None
        try:
            parsed = extract_json_object(raw)
        except Exception:
            repaired_raw = repair_with_second_call(bridge, raw or '')
            (raw_dir / f'{category}_{item_id}.repair.txt').write_text(repaired_raw or '', encoding='utf-8')
            parsed = extract_json_object(repaired_raw)

        results.append({
            'item': item,
            'raw_output': raw,
            'repair_output': repaired_raw,
            'parsed_output': parsed,
            'prompt_path': str(prompt_path),
            'provider': getattr(getattr(bridge, 'provider', None), 'name', None),
            'model': getattr(getattr(bridge, 'provider', None), 'model', None),
        })

    out_path = out_dir / f'{category}_{len(results)}_reverse_query_results.json'
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {
        'category': category,
        'count': len(results),
        'output_path': str(out_path),
        'ids': [r['item'].get('id') for r in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Direct reverse-query runner for youware_0423 prompts')
    parser.add_argument('--input', default=str(ROOT / 'inputs' / 'category15_input.json'))
    parser.add_argument('--categories', nargs='+', default=['game', 'dashboard'])
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--out-dir', default=str(ROOT / 'outputs' / 'direct_reverse_query'))
    args = parser.parse_args()

    items = load_items(Path(args.input))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {'runs': []}
    for category in args.categories:
        if category not in PROMPT_MAP:
            raise ValueError(f'unsupported category: {category}')
        summary['runs'].append(run_category(items, category, args.limit, out_dir))

    summary_path = out_dir / 'run_summary.json'
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
