#!/usr/bin/env python3
"""D班 追加突合2:
- BLKTYTBL 第1リスト: サブ（バリエーション）間の関係を検証
  仮説: 同一図のサブ間で第1リストは互いに素で、和集合が第2リスト/U と一致
- IBHTBL: キー付きで後続文字のあるレコードの実例
- PLGKTBL C: 全80件の値と、該当カタログのモデル号機帯
"""
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


def parse_blkty(data):
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        fk = rec[2:9].decode('ascii', 'replace')
        key = (fk[0:3].strip(), fk[3:5].strip(), fk[5:7].strip())
        (l1,) = struct.unpack_from('<H', rec, 85)
        list1 = [struct.unpack_from('<H', rec, j)[0]
                 for j in range(87, 87 + l1, 2)]
        list2 = [struct.unpack_from('<H', rec, j)[0]
                 for j in range(87 + l1, len(rec) - 1, 2)]
        recs.append({'key': key, 'list1': list1, 'list2': list2})
        off += ln
    return recs


print('===== BLKTYTBL 第1リスト: サブ間関係')
stats = Counter()
for cat in CATS:
    blk = parse_blkty(open(os.path.join(WORK, cat, 'BLKTYTBL.CD'), 'rb').read())
    byfig = defaultdict(list)
    for b in blk:
        byfig[(b['key'][0], b['key'][1])].append(b)
    for fig, subs in byfig.items():
        if len(subs) < 2:
            continue
        stats['multi_sub_figs'] += 1
        sets = [set(s['list1']) for s in subs]
        disjoint = all(not (sets[i] & sets[j])
                       for i in range(len(sets)) for j in range(i + 1, len(sets)))
        if disjoint:
            stats['list1_disjoint_across_subs'] += 1
        u1 = set().union(*sets) if sets else set()
        l2s = [set(s['list2']) for s in subs]
        if all(u1 == l2 for l2 in l2s):
            stats['union_list1_eq_each_list2'] += 1
        if u1 == set().union(*l2s):
            stats['union_list1_eq_union_list2'] += 1
        if all(set(s['list1']) <= set(s['list2']) for s in subs):
            stats['each_list1_subset_own_list2'] += 1
print(dict(stats))

# シティ E-1 の全サブを実例として出す
blk = parse_blkty(open(os.path.join(WORK, '11SA702', 'BLKTYTBL.CD'), 'rb').read())
for b in blk:
    if b['key'][0] == 'E' and b['key'][1] == '1':
        print('  E-1 sub=%r list1=%s list2=%s' % (b['key'][2], b['list1'], b['list2']))

print()
print('===== IBHTBL キー付き＋後続文字あり の実例')
shown = 0
for cat in CATS:
    try:
        data = get(cat, 'IBHTBL.CD')
    except Exception:
        continue
    off = 0
    while off + 2 <= len(data) and shown < 25:
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        key = rec[2:12].decode('ascii', 'replace').strip()
        (cnt,) = struct.unpack_from('<H', rec, 12)
        chars = rec[14:].decode('ascii', 'replace')
        if key and chars:
            print(f'  {cat}: key={key!r} cnt={cnt} chars={chars!r}')
            shown += 1
        off += ln

print()
print('===== PLGKTBL C 全件（値のみ）')
db = sqlite3.connect(os.path.join(BASE, 'epc_index.sqlite'))
for cat in ['1168005', '11SB001', '11SB601', '11SC902', '11SD501', '11SD511',
            '11SF101', '11SH201', '11SH301', '11SH401', '11SH501', '11SJ701']:
    data = get(cat, 'PLGKTBL.CD')
    crec = []
    for i in range(0, len(data) - 16, 17):
        rec = data[i:i + 17]
        if chr(rec[0]) == 'C':
            crec.append((rec[1:9].decode('ascii', 'replace').strip(),
                         rec[9:17].decode('ascii', 'replace').strip()))
    names = db.execute(
        'SELECT DISTINCT name, type_full FROM models WHERE catalog=?', (cat,)).fetchall()
    print(f'  {cat} {names}: C={crec}')
iso.close()
