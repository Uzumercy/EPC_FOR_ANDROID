#!/usr/bin/env python3
"""Collect and classify PLMST tail parse failures across all 82 catalogs.

For each failing record: catalog, figkey, partno, tail length, tail hex,
the standard start candidate, and whether a brute-force start offset
(0..48) lets parse_chain consume the tail exactly.
"""
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.expanduser('~/workspace/epc-project/converter'))
from epcconv.parsers import parse_plmst, parse_tail, parse_chain  # noqa: E402

BASE = os.path.expanduser('~/workspace/epc-project')
PLMST_DIR = os.path.join(BASE, 'cd/plmst_all')
OUT = os.path.join(BASE, 'analysis/work/tail_failures.tsv')

rows = []
total = 0
for fn in sorted(os.listdir(PLMST_DIR)):
    cat = fn.replace('_PLMST.CD', '')
    data = open(os.path.join(PLMST_DIR, fn), 'rb').read()
    for fk, pn, nm, pr, tail in parse_plmst(data):
        total += 1
        if parse_tail(tail) is not None:
            continue
        brute = [s for s in range(0, 49) if parse_chain(tail, s) is not None]
        rows.append((cat, fk, pn, len(tail), tail.hex(), brute))

print('total records', total)
print('failures', len(rows))
print('brute-force rescued', sum(1 for r in rows if r[5]))
print('tail length distribution', Counter(r[3] for r in rows).most_common(12))
print('by catalog', Counter(r[0] for r in rows).most_common(10))
with open(OUT, 'w') as f:
    for r in rows:
        f.write('\t'.join([r[0], r[1], r[2], str(r[3]), r[4],
                           ','.join(map(str, r[5]))]) + '\n')
print('wrote', OUT)
for r in rows[:15]:
    print(r[0], r[1], r[2], 'tailen', r[3], 'brute', r[5], r[4][:80])
