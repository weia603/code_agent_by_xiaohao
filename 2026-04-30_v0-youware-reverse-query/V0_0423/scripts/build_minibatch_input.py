#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path('/data/openclaw/V0_0423')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / 'inputs' / 'minibatch_input.json'))
    args = parser.parse_args()

    samples = [
        {
            'id': 'mini-game-001',
            'title': 'Dungeon Key Run',
            'summary': 'A browser dungeon mini game with keys, enemies, treasure and restart.',
            'text': 'Players move through dungeon rooms, collect keys, avoid enemy collision, pick up treasure, increase score, and restart after game over.',
            'preset_category': 'game'
        },
        {
            'id': 'mini-game-002',
            'title': 'Math Cannon Rush',
            'summary': 'An educational shooting game built around quick arithmetic.',
            'text': 'Players answer math questions to fire at targets, gain points, lose lives on mistakes, and replay after the round ends.',
            'preset_category': 'game'
        },
        {
            'id': 'mini-game-003',
            'title': 'Fruit Merge Pop',
            'summary': 'A casual merge game with combo scoring and retry loop.',
            'text': 'Drag matching fruit to merge them, trigger combo feedback, hit score milestones, and retry levels after failure.',
            'preset_category': 'game'
        }
    ]

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'items': samples}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'count': len(samples), 'output': str(out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
