#!/usr/bin/env python3
"""D班 追加突合:
- IBHTBL: 全レコードを (キー有無, [12:14]値, 後続文字列) で再分類する
- PLGKTBL: キー × 値形式（数字のみ/英数字）の分布を全カタログで取る
- BLKTYTBL 第1リスト: 値の分布と、値を保持するモデルの数との関係
"""
import json
import os
import sqlite3
import struct
import sys
from collections import Counter, defaultdict

BASE = os.path.expanduser('~/workspace/epc-project')
sys.path.insert(0, os.path.join(BASE, 'analysis'))
import iso_index  # noqa: E402

iso = iso_index.open_iso()
files = iso_index.load()
WORK = os.path.join(BASE, 'analysis/work')
CATS = sorted({p.split('/')[1] for p in files
               if p.count('/') >= 2 and not p.startswith('/PROGRAM')})
CATS = [c for c in CATS if c and os.path.isdir(os.path.join(WORK, c))]


def get(cat, name):
    return iso_index.get(iso, f'/{cat}/{name}')


# ---------- IBHTBL ----------
print('===== IBHTBL 再分類')
city = []
combo = Counter()
for cat in CATS:
    try:
        data = get(cat, 'IBHTBL.CD')
    except Exception:
        continue
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        key = rec[2:12].decode('ascii', 'replace').strip()
        (cnt,) = struct.unpack_from('<H', rec, 12)
        chars = rec[14:].decode('ascii', 'replace')
        combo[(bool(key), cnt, len(chars))] += 1
        if cat == '11SA702':
            city.append((key, cnt, chars))
        off += ln
print('(キー有, [12:14]値, 後続文字数) -> 件数')
for k in sorted(combo):
    print(' ', k, combo[k])
print('--- 11SA702 全レコード (key, cnt, chars)')
for row in city:
    print(' ', row)

# ---------- PLGKTBL ----------
print('===== PLGKTBL キー×値形式')
form_by_key = defaultdict(Counter)
cats_with_alpha = defaultdict(set)
for cat in CATS:
    data = get(cat, 'PLGKTBL.CD')
    for i in range(0, len(data) - 16, 17):
        rec = data[i:i + 17]
        key = chr(rec[0])
        frm = rec[1:9].decode('ascii', 'replace').strip()
        to = rec[9:17].decode('ascii', 'replace').strip()
        for v in (frm, to):
            if not v:
                continue
            form = 'numeric' if v.replace(' ', '').isdigit() else 'alnum'
            form_by_key[key][form] += 1
            if form == 'alnum':
                cats_with_alpha[key].add(cat)
for key in sorted(form_by_key):
    print(f'  key {key}: {dict(form_by_key[key])}, alnumのあるカタログ数={len(cats_with_alpha[key])}')
print('  C の英数字があるカタログ:', sorted(cats_with_alpha['C']))
for key in 'EFM':
    print(f'  {key} の英数字があるカタログ:', sorted(cats_with_alpha[key]))

# ---------- BLKTYTBL 第1リストの値 ----------
print('===== BLKTYTBL 第1リスト値の性質')
db = sqlite3.connect(os.path.join(BASE, 'epc_index.sqlite'))
models = defaultdict(list)
for cat, ids in db.execute('SELECT catalog, ids FROM models'):
    if ids:
        models[cat].append([int(x) for x in ids.split(',') if x.strip()])
val_stats = Counter()
carriers = Counter()
maxid = {}
for cat in CATS:
    ms = models.get(cat, [])
    allids = set()
    for m in ms:
        allids.update(m)
    maxid[cat] = max(allids) if allids else 0
    # value -> number of models carrying it
    carry = Counter()
    for m in ms:
        for v in set(m):
            carry[v] += 1
    data = open(os.path.join(WORK, cat, 'BLKTYTBL.CD'), 'rb').read()
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        (l1,) = struct.unpack_from('<H', rec, 85)
        A = [struct.unpack_from('<H', rec, j)[0] for j in range(87, 87 + l1, 2)]
        for v in A:
            val_stats['values_total'] += 1
            if v in allids:
                val_stats['value_in_catalog_idspace'] += 1
            c = carry.get(v, 0)
            carriers[c if c <= 5 else '6+'] += 1
            if c == len(ms):
                val_stats['value_carried_by_all_models'] += 1
            if c == 1:
                val_stats['value_carried_by_exactly_1_model'] += 1
        off += ln
print(dict(val_stats))
print('値を保持するモデル数ごとの分布:', dict(sorted(carriers.items(), key=lambda kv: str(kv[0]))))
iso.close()
