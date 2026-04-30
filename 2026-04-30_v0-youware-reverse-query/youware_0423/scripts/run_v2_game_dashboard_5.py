#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path('/data/openclaw/youware_0423')
SOURCE_ROOT = Path('/data/openclaw/youware')
SCRIPTS = SOURCE_ROOT / 'scripts'

sys.path.insert(0, str(SCRIPTS))

from common.llm_bridge import PromptPackage, create_bridge  # type: ignore

GAME_PROMPT = ROOT / 'prompts' / '21_query_generation_game_v2.md'
DASHBOARD_PROMPT = ROOT / 'prompts' / '22_query_generation_dashboard_v2.md'
AI_APP_PROMPT = ROOT / 'prompts' / '23_query_generation_ai_app_v2.md'
EDUCATION_PROMPT = ROOT / 'prompts' / '24_query_generation_education_v2.md'
LANDING_PAGE_PROMPT = ROOT / 'prompts' / '25_query_generation_landing_page_v2.md'
PRESENTATION_PROMPT = ROOT / 'prompts' / '26_query_generation_presentation_v2.md'
PRODUCTIVITY_TOOL_PROMPT = ROOT / 'prompts' / '27_query_generation_productivity_tool_v2.md'
INPUT_PATH = ROOT / 'inputs' / 'category15_input.json'
OUT_DIR = ROOT / 'outputs' / 'v2_runs'


def load_items() -> list[dict[str, Any]]:
    data = json.loads(INPUT_PATH.read_text(encoding='utf-8'))
    return data['items']


def select_items(items: list[dict[str, Any]], category: str, limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for item in items:
        if item.get('preset_category') == category:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def make_package(prompt_path: Path) -> PromptPackage:
    pkg = PromptPackage(prompt_dir=prompt_path.parent)
    filename = prompt_path.name
    pkg.resolve = lambda prompt_name, category=None: prompt_path  # type: ignore
    pkg.load = lambda prompt_name, category=None: (prompt_path, prompt_path.read_text(encoding='utf-8'))  # type: ignore
    return pkg


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
        'item': row,
        'extract': extract.output,
        'extract_meta': extract.to_meta(),
        'normalize': normalize.output,
        'normalize_meta': normalize.to_meta(),
    }


def main() -> int:
    mode = os.getenv('LLM_BRIDGE_MODE', 'auto')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    items = load_items()
    plan = [
        ('game', GAME_PROMPT),
        ('dashboard', DASHBOARD_PROMPT),
    ]
    summary = {}
    for category, prompt_path in plan:
        chosen = select_items(items, category, limit=5)
        results = [run_one(item, prompt_path, mode) for item in chosen]
        out_path = OUT_DIR / f'{category}_5_results.json'
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        summary[category] = {
            'count': len(results),
            'output_path': str(out_path),
            'prompt_path': str(prompt_path),
            'ids': [r['item']['item_id'] for r in results],
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
