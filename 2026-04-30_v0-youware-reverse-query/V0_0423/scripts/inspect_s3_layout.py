#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import megfile

S3_PREFIX = 's3://collect-data-text/202511/h5sites_resource/v0/20260302/apps-and-games/'
ROOT = Path('/data/openclaw/V0_0423')


def list_s3(prefix: str, limit: int = 200) -> list[str]:
    out = []
    for path in megfile.smart_glob(prefix.rstrip('/') + '/*'):
        out.append(path)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / 'notes' / 's3_ls_top.json'))
    parser.add_argument('--limit', type=int, default=200)
    args = parser.parse_args()

    paths = list_s3(S3_PREFIX, limit=args.limit)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'prefix': S3_PREFIX,
        'count': len(paths),
        'paths': paths,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'count': len(paths), 'output': str(out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
