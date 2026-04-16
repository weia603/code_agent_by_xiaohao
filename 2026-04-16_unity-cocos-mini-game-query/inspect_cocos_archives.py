#!/usr/bin/env python3
"""
Lightweight inspector for Cocos/game source archives on S3.
Lists archive entries without full extraction and emits JSONL summaries for LLM reverse-query generation.
Supports zip and rar via bsdtar fallback without full extraction.
"""

import argparse
import hashlib
import json
import os
import posixpath
import re
import subprocess
import tempfile
from urllib.parse import unquote

from megfile import smart_copy, smart_isdir, smart_listdir

ALLOWED_SUFFIXES = ('.zip', '.rar', '.7z')
GAME_TAGS = [
    '消除', '合成', '跑酷', '赛车', '坦克', '射击', '打砖块', '贪吃蛇', '捕鱼', '答题', '拼图', '音乐',
    '球', '飞刀', '矿工', '斗地主', '麻将', '扑克', '大冒险', '跳跃', '俄罗斯方块', '泡泡龙', '推箱子',
    '华容道', '找你妹', '密室逃脱', '塔', '战机', '足球', '篮球', '卡牌', '模拟器', '停车', '划线', '割草', '羊了个羊', '一笔画'
]
TECH_TAGS = ['creator', 'cocos', 'laya', 'egret', '白鹭', 'unity', '3d', 'h5', 'ts', 'js']


def md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def iter_files(prefix: str, max_depth: int):
    def walk(path: str, depth: int):
        for name in smart_listdir(path):
            child = path.rstrip('/') + '/' + name
            try:
                is_dir = smart_isdir(child)
            except Exception:
                is_dir = False
            if is_dir and depth < max_depth:
                yield from walk(child + '/', depth + 1)
            elif child.lower().endswith(ALLOWED_SUFFIXES):
                yield child
    yield from walk(unquote(prefix), 0)


def run_cmd(cmd):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, '', repr(e)


def parse_7z_list_output(out: str):
    lines = []
    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue
        parts = re.split(r'\s{2,}', s)
        if parts:
            lines.append(parts[-1])
    return lines


def list_archive(local_path: str):
    lower = local_path.lower()
    if lower.endswith('.zip'):
        for cmd in (["zipinfo", "-1", local_path], ["unzip", "-Z1", local_path], ["bsdtar", "-tf", local_path]):
            code, out, err = run_cmd(cmd)
            if code == 0 and out.strip():
                return [x.strip() for x in out.splitlines() if x.strip()], ''
        return [], 'zip_list_failed'
    if lower.endswith('.rar'):
        for cmd in (["bsdtar", "-tf", local_path], ["unrar", "lb", local_path], ["7z", "l", "-ba", local_path]):
            code, out, err = run_cmd(cmd)
            if code == 0 and out.strip():
                if cmd[0] == '7z':
                    return parse_7z_list_output(out), ''
                return [x.strip() for x in out.splitlines() if x.strip()], ''
        return [], 'rar_list_failed'
    if lower.endswith('.7z'):
        for cmd in (["7z", "l", "-ba", local_path], ["bsdtar", "-tf", local_path]):
            code, out, err = run_cmd(cmd)
            if code == 0 and out.strip():
                if cmd[0] == '7z':
                    return parse_7z_list_output(out), ''
                return [x.strip() for x in out.splitlines() if x.strip()], ''
        return [], '7z_list_failed'
    return [], 'unsupported_suffix'


def summarize_archive(source_path: str):
    name = posixpath.basename(source_path)
    tags = [t for t in GAME_TAGS if t in name]
    tech = [t for t in TECH_TAGS if t.lower() in name.lower()]
    with tempfile.TemporaryDirectory(prefix='game_reverse_') as td:
        local_path = os.path.join(td, name)
        smart_copy(source_path, local_path)
        entries, list_error = list_archive(local_path)
    entries = entries[:400]
    top_dirs = []
    key_files = []
    engine_signals = set(tech)
    gameplay_signals = set(tags)
    ui_signals = []
    for e in entries:
        parts = [p for p in e.split('/') if p]
        if parts:
            if parts[0] not in top_dirs:
                top_dirs.append(parts[0])
        low = e.lower()
        if any(sig in low for sig in ['project.json', 'settings', 'assets', 'scenes', 'scene', 'prefab', 'package.json', 'tsconfig', 'main.js', 'game.js', 'resultview', 'homeview', 'shopview', 'energyview', 'rankingview', 'reviveview']):
            key_files.append(e)
        if any(sig in low for sig in ['homeview', 'resultview', 'shopview', 'energyview', 'touchview', 'rankingview', 'reviveview', 'battleview', 'gameoverview']):
            ui_signals.append(e)
        for t in TECH_TAGS:
            if t.lower() in low:
                engine_signals.add(t)
        for g in GAME_TAGS:
            if g in e:
                gameplay_signals.add(g)
    return {
        'sample_id': md5(source_path),
        'source_path': source_path,
        'file_name': name,
        'source_type': 'cocos_game_archive',
        'archive_summary': {
            'entry_count_sampled': len(entries),
            'top_level_dirs': top_dirs[:30],
            'key_files': key_files[:80],
            'engine_signals': sorted(engine_signals),
            'gameplay_signals': sorted(gameplay_signals),
            'ui_signals': ui_signals[:30],
            'entry_name_samples': entries[:150],
            'list_error': list_error,
        }
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-prefix', required=True)
    ap.add_argument('--output-jsonl', required=True)
    ap.add_argument('--max-depth', type=int, default=4)
    ap.add_argument('--limit', type=int, default=12)
    args = ap.parse_args()

    count = 0
    os.makedirs(os.path.dirname(args.output_jsonl), exist_ok=True)
    with open(args.output_jsonl, 'w', encoding='utf-8') as w:
        for path in iter_files(args.input_prefix, args.max_depth):
            row = summarize_archive(path)
            w.write(json.dumps(row, ensure_ascii=False) + '\n')
            w.flush()
            count += 1
            if count >= args.limit:
                break
    print(json.dumps({'output_jsonl': args.output_jsonl, 'count': count}, ensure_ascii=False))


if __name__ == '__main__':
    main()
