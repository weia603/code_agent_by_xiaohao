#!/usr/bin/env python3
"""
Lightweight inspector for Unity game archives on S3.
Goal: infer the final product shape (game/product experience) rather than implementation details.
It classifies archives into likely complete products vs templates/frameworks/asset packs.
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
PRODUCT_KEYWORDS = [
    'pacman', 'mario', 'runner', 'shoot', 'shooter', 'top down', 'zombie', 'puzzle', 'tank',
    'snake', 'tower', 'defense', 'platform', 'platformer', '2048', 'tetris', 'racing', 'car',
    'football', 'basketball', 'pinball', 'ninja', 'fruit', 'bird', 'farm', 'jump', 'dungeon'
]
PRODUCT_KEYWORDS_ZH = [
    '跑酷', '吃豆人', '马里奥', '射击', '坦克', '僵尸', '益智', '合成', '闯关', '经营', '农场',
    '跳跃', '俄罗斯方块', '赛车', '篮球', '足球', '忍者', '飞行', '消除', '塔防'
]
TEMPLATE_HINTS = [
    'starter kit', 'framework', 'toolkit', 'template', 'asset pack', 'demo kit', 'sample pack'
]
UI_HINTS = [
    'mainmenu', 'start', 'login', 'levelselect', 'gamescene', 'result', 'win', 'lose', 'shop', 'upgrade', 'settings'
]
SYSTEM_HINTS = [
    'score', 'coin', 'gold', 'hp', 'health', 'energy', 'skill', 'inventory', 'quest', 'reward', 'ad', 'revive'
]
FEEDBACK_HINTS = [
    'hit', 'boom', 'shoot', 'jump', 'combo', 'win', 'lose', 'bgm', 'explosion', 'coin'
]
UNITY_STRUCT_HINTS = [
    'assets/', 'projectsettings/', 'packages/', '.unity', '.prefab', '.cs', '.asset', '.controller', '.anim', '.mat', '.shader', 'assembly-csharp.csproj'
]


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


def classify_product_type(name: str, entries):
    low_name = name.lower()
    low_entries = '\n'.join(e.lower() for e in entries[:400])

    if any(h in low_name for h in TEMPLATE_HINTS) or any(h in low_entries for h in TEMPLATE_HINTS):
        return 'starter_kit_or_template'

    unity_struct_score = sum(1 for h in UNITY_STRUCT_HINTS if h in low_entries)
    ui_score = sum(1 for h in UI_HINTS if h in low_entries)
    sys_score = sum(1 for h in SYSTEM_HINTS if h in low_entries)
    feedback_score = sum(1 for h in FEEDBACK_HINTS if h in low_entries)
    product_score = sum(1 for h in PRODUCT_KEYWORDS if h in low_name or h in low_entries)
    product_score += sum(1 for h in PRODUCT_KEYWORDS_ZH if h in name or h in ''.join(entries[:200]))

    # asset/resource heavy but weak gameplay signals
    asset_heavy = (
        low_entries.count('.png') + low_entries.count('.jpg') + low_entries.count('.fbx') + low_entries.count('.mat')
    ) >= 20 and product_score <= 1 and ui_score == 0 and sys_score == 0

    if asset_heavy:
        return 'asset_pack_or_resource_pack'

    if unity_struct_score >= 3 and (product_score + ui_score + sys_score + feedback_score) >= 4:
        return 'complete_game_project'

    if unity_struct_score >= 2 and product_score <= 1 and ui_score == 0 and sys_score <= 1:
        return 'framework_or_toolkit'

    return 'unclear_or_sparse'


def summarize_archive(source_path: str):
    name = posixpath.basename(source_path)
    with tempfile.TemporaryDirectory(prefix='unity_reverse_') as td:
        local_path = os.path.join(td, name)
        smart_copy(source_path, local_path)
        entries, list_error = list_archive(local_path)
    entries = entries[:500]

    top_dirs = []
    key_files = []
    product_hints = []
    ui_hints = []
    system_hints = []
    feedback_hints = []
    unity_structure = []

    for e in entries:
        parts = [p for p in e.split('/') if p]
        if parts and parts[0] not in top_dirs:
            top_dirs.append(parts[0])
        low = e.lower()

        if any(h in low for h in UNITY_STRUCT_HINTS):
            unity_structure.append(e)
        if any(h in low for h in UI_HINTS):
            ui_hints.append(e)
        if any(h in low for h in SYSTEM_HINTS):
            system_hints.append(e)
        if any(h in low for h in FEEDBACK_HINTS):
            feedback_hints.append(e)
        if any(h in low for h in PRODUCT_KEYWORDS) or any(h in e for h in PRODUCT_KEYWORDS_ZH):
            product_hints.append(e)
        if any(sig in low for sig in ['.unity', '.prefab', '.cs', '.anim', '.controller', 'mainmenu', 'gamescene', 'player', 'enemy', 'score', 'shop', 'level']):
            key_files.append(e)

    product_type = classify_product_type(name, entries)

    return {
        'sample_id': md5(source_path),
        'source_path': source_path,
        'file_name': name,
        'source_type': 'unity_game_archive',
        'archive_summary': {
            'product_type_guess': product_type,
            'entry_count_sampled': len(entries),
            'top_level_dirs': top_dirs[:30],
            'key_files': key_files[:100],
            'product_hints': product_hints[:60],
            'ui_hints': ui_hints[:40],
            'system_hints': system_hints[:40],
            'feedback_hints': feedback_hints[:40],
            'unity_structure_hints': unity_structure[:60],
            'entry_name_samples': entries[:180],
            'list_error': list_error,
        }
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-prefix', required=True)
    ap.add_argument('--output-jsonl', required=True)
    ap.add_argument('--max-depth', type=int, default=8)
    ap.add_argument('--limit', type=int, default=20)
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
