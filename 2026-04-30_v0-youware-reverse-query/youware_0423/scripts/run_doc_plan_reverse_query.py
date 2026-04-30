#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path('/data/openclaw/youware_0423')
SOURCE_ROOT = Path('/data/openclaw/youware')
SCRIPTS = SOURCE_ROOT / 'scripts'

import sys
sys.path.insert(0, str(SCRIPTS))

from common.llm_bridge import PromptPackage, create_bridge  # type: ignore

PROMPT_MAP = {
    'game': ROOT / 'prompts' / '21_query_generation_game_v2.md',
    'dashboard': ROOT / 'prompts' / '22_query_generation_dashboard_v2.md',
}

CATEGORY1_TO_CATEGORY2 = {
    '工程级应用': [
        'AI前端应用', '中后台管理', '电商', '社区', '内容平台',
        '富文本编辑器应用', '图像编辑应用', '视频剪辑工具', '即时通讯',
        '低代码/流程引擎应用', '跨端应用', '桌面应用', '物联网和嵌入式',
    ],
    '内容站点': [
        '博客/新闻', '营销/着陆页', '作品集/官网', '文档/维基',
    ],
    '互动娱乐': [
        '单页工具', '小游戏', '互动媒体/艺术', '可视化', 'SVG',
    ],
}

PRESET_TO_FINAL_CATEGORY = {
    'game': ('互动娱乐', '小游戏', True),
    'dashboard': ('互动娱乐', '可视化', False),
    'productivity-tool': ('互动娱乐', '单页工具', False),
    'ai-app': ('工程级应用', 'AI前端应用', False),
    'presentation': ('内容站点', '营销/着陆页', False),
}

OUT_DIR = ROOT / 'outputs' / 'doc_plan_runs'


def load_items(input_path: Path) -> list[dict[str, Any]]:
    data = json.loads(input_path.read_text(encoding='utf-8'))
    items = data['items'] if isinstance(data, dict) and 'items' in data else data
    if not isinstance(items, list):
        raise ValueError('input must be a list or an object with items[]')
    return items


def select_items(items: list[dict[str, Any]], category: str, limit: int) -> list[dict[str, Any]]:
    out = []
    for item in items:
        if item.get('preset_category') == category:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def make_package(prompt_path: Path) -> PromptPackage:
    pkg = PromptPackage(prompt_dir=prompt_path.parent)
    pkg.resolve = lambda prompt_name, category=None: prompt_path  # type: ignore
    pkg.load = lambda prompt_name, category=None: (prompt_path, prompt_path.read_text(encoding='utf-8'))  # type: ignore
    return pkg


def infer_is_complete(item: dict[str, Any]) -> tuple[bool, str]:
    text = ' '.join(str(item.get(k, '') or '') for k in ['title', 'summary', 'text', 'visible_text', 'dom_summary', 'ocr_text'])
    strong_signals = 0
    if len(text) >= 80:
        strong_signals += 1
    if re.search(r'\b(score|level|timer|lives|restart|game over|kpi|trend|chart|filter|map|drill|sla|queue|heatmap)\b', text, re.I):
        strong_signals += 1
    if re.search(r'\b(click|drag|keyboard|touch|retry|pause|export|preview|panel|card|widget|navigation)\b', text, re.I):
        strong_signals += 1
    is_complete = strong_signals >= 2
    if is_complete:
        return True, '证据中已包含较明确的主任务、关键交互或页面结构，可支撑专业级逆向。'
    return False, '当前证据偏局部或信息不足，但仍可基于已知题材、结构和交互信号生成保守版需求。'


def normalize_feature_query(raw: str) -> str:
    raw = (raw or '').strip()
    if not raw:
        return '1. 明确主任务与核心页面结构。\n2. 补充关键交互和状态反馈。\n3. 输出可直接用于实现的高信息密度需求。'
    if re.search(r'(^|\n)\s*1\.', raw):
        return raw
    parts = [x.strip(' -•\n\t') for x in raw.splitlines() if x.strip()]
    if not parts:
        return raw
    return '\n'.join(f'{i+1}. {part}' for i, part in enumerate(parts[:5]))


def build_queries(product_query: str, feature_query: str, fallback_title: str) -> list[str]:
    product_query = (product_query or '').strip()
    lines = [x.strip() for x in re.split(r'\n+', feature_query or '') if x.strip()]
    feature_brief = '；'.join(re.sub(r'^\d+\.\s*', '', x) for x in lines[:3])
    candidates = []
    if product_query:
        candidates.append(product_query)
        if feature_brief:
            candidates.append(f'{product_query}，并且要包含：{feature_brief}')
        candidates.append(f'设计一个围绕“{fallback_title}”主题展开的前端产品，要求主需求是：{product_query}')
    else:
        candidates.append(f'基于“{fallback_title}”做一个高质量前端产品需求，补全主任务、页面结构和关键交互。')
    dedup = []
    seen = set()
    for q in candidates:
        if q not in seen:
            dedup.append(q)
            seen.add(q)
    return dedup[:4]


def postprocess_result(item: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    preset = item.get('preset_category', '')
    category1, category2, is_game = PRESET_TO_FINAL_CATEGORY.get(preset, ('工程级应用', '中后台管理', False))
    complete, complete_reason = infer_is_complete(item)

    parsed = dict(result.get('normalize', {}) or {})
    extract = dict(result.get('extract', {}) or {})

    product_query = (extract.get('product_query') or '').strip()
    feature_query = normalize_feature_query(extract.get('feature_query') or '')
    queries = parsed.get('queries') or extract.get('queries') or []
    if not isinstance(queries, list):
        queries = []
    if not queries:
        queries = build_queries(product_query, feature_query, item.get('title', '未命名样本'))

    if is_game:
        category_reason = '证据中存在明确玩法目标、玩家输入与游戏状态流转信号，因此判定为小游戏。'
    else:
        category_reason = f'该样本更像“{category1}/{category2}”而非小游戏，核心价值在于{item.get("summary", "页面功能与信息组织")}。'

    return {
        'item': {
            'id': item.get('id'),
            'title': item.get('title', ''),
            'summary': item.get('summary', ''),
            'preset_category': preset,
        },
        'product_query': product_query,
        'feature_query': feature_query,
        'is_complete': complete,
        'reason': complete_reason,
        'category1': category1,
        'category2': category2,
        'category_is_game': is_game,
        'category_decision_reason': category_reason,
        'queries': queries[:4],
        'extract_meta': result.get('extract_meta', {}),
        'normalize_meta': result.get('normalize_meta', {}),
    }


def run_one(item: dict[str, Any], prompt_path: Path, mode: str) -> dict[str, Any]:
    bridge = create_bridge(mode)
    bridge.prompt_package = make_package(prompt_path)
    row = {
        'item_id': item['id'],
        'title': item.get('title', ''),
        'summary': item.get('summary', ''),
        'text': item.get('text', ''),
        'preset_category': item.get('preset_category', ''),
    }
    extract = bridge.run_extract(row)
    normalize = bridge.run_normalize({
        'item_id': row['item_id'],
        'title': row['title'],
        'summary': row['summary'],
        'evidence_text': row['text'],
        'preset_category': row['preset_category'],
        **extract.output,
    })
    return {
        'extract': extract.output,
        'extract_meta': extract.to_meta(),
        'normalize': normalize.output,
        'normalize_meta': normalize.to_meta(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Run reverse-query generation aligned to 0423 plan doc')
    parser.add_argument('--input', default=str(ROOT / 'inputs' / 'category15_input.json'))
    parser.add_argument('--categories', nargs='+', default=['game', 'dashboard'])
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--output-dir', default=str(OUT_DIR))
    args = parser.parse_args()

    mode = os.getenv('LLM_BRIDGE_MODE', 'auto')
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    items = load_items(Path(args.input))

    summary: dict[str, Any] = {'mode': mode, 'runs': []}
    for category in args.categories:
        prompt_path = PROMPT_MAP[category]
        chosen = select_items(items, category, args.limit)
        results = []
        for item in chosen:
            raw = run_one(item, prompt_path, mode)
            results.append(postprocess_result(item, raw))
        out_path = out_dir / f'{category}_{len(results)}_doc_plan_results.json'
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        summary['runs'].append({
            'category': category,
            'count': len(results),
            'output_path': str(out_path),
            'ids': [x['item']['id'] for x in results],
        })

    (out_dir / 'run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
