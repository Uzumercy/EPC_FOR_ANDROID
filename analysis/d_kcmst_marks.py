#!/usr/bin/env python3
"""D班 項目1: KCMST の # / * 付き値レコード（注記込み）をカタログ別に集計・表示し、
# が多いカタログの90番ページ先頭ファイルをデコード対象として洗い出す。"""
import os
import struct
import sys
from collections import Counter

BASE = os.path.expanduser('~/workspace/epc-project')
sys.path.insert(0, os.path.join(BASE, 'analysis'))
import iso_index  # noqa: E402

iso = iso_index.open_iso()
files = iso_index.load()
CATS = sorted({p.split('/')[1] for p in files
               if p.count('/') >= 2 and not p.startswith('/PROGRAM')})
CATS = [c for c in CATS if c and len(c) == 7]


def parse_kcmst(data):
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        name = rec[2:52].decode('cp932', 'replace').strip()
        val = rec[52:57].decode('ascii', 'replace').strip()
        notes = []
        for i in range(57, ln - 59, 60):
            t = rec[i:i + 60].decode('cp932', 'replace').strip()
            if t:
                notes.append(t)
        recs.append((name, val, notes))
        off += ln
    return recs


hash_count = Counter()
star_count = Counter()
for cat in CATS:
    try:
        recs = parse_kcmst(iso_index.get(iso, f'/{cat}/KCMST.CD'))
    except Exception:
        continue
    for name, val, notes in recs:
        if val.startswith('#'):
            hash_count[cat] += 1
        if val.startswith('*'):
            star_count[cat] += 1
print('# の多いカタログ:', hash_count.most_common(8))
print('* の多いカタログ:', star_count.most_common(8))

print()
print('--- 11SA702 の # 付きレコード（注記込み、先頭20件）')
recs = parse_kcmst(iso_index.get(iso, '/11SA702/KCMST.CD'))
n = 0
for name, val, notes in recs:
    if val.startswith('#') and n < 20:
        print(f'  {val:>6} {name}  注記={notes}')
        n += 1
print('--- 11SA702 の * 付きレコード（先頭15件）')
n = 0
for name, val, notes in recs:
    if val.startswith('*') and n < 15:
        print(f'  {val:>6} {name}  注記={notes}')
        n += 1
iso.close()
