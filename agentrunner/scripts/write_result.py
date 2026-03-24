#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone

def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--json', required=True, dest='json_text')
    args = ap.parse_args()
    obj = json.loads(args.json_text)
    obj.setdefault('writtenAt', iso_now())
    os.makedirs(os.path.dirname(args.path), exist_ok=True)
    tmp = args.path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, args.path)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
