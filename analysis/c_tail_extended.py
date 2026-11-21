#!/usr/bin/env python3
"""Test an extended PLMST tail grammar over the full corpus.

Extension: in a type-B group the remark field is a FIXED 3-byte field
starting with '(' (e.g. '(8)', '(14', '(16').  The current parser searches
for ')' and fails when the remark holds a two-digit number (no ')' fits).
With the fixed-field rule, codes start at group+9 exactly as for type A.

Checks:
- total parse successes with the extended grammar (old: 609,705/609,952)
- for records the old grammar already parsed, the extended grammar must
  produce identical groups (no reinterpretation)
- census of all remark strings
"""
import os
import re
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.expanduser('~/workspace/epc-project/converter'))
from epcconv.parsers import parse_plmst, parse_tail, _QTY_FIELD  # noqa: E402

BASE = os.path.expanduser('~/workspace/epc-project')
PLMST_DIR = os.path.join(BASE, 'cd/plmst_all')
remarks = Counter()


def parse_chain_ext(tail, start):
    groups = []
    i = start
    while i < len(tail):
        if i + 9 > len(tail):
            return None
        glen = struct.unpack('<H', tail[i:i + 2])[0]
        if glen < 9 or i + glen > len(tail):
            return None
        f3 = tail[i + 6:i + 9]
        if f3[:1] == b'(':
            # type B: fixed 3-byte remark field
            if (glen - 9) % 2:
                return None
            codes = [struct.unpack('<H', tail[j:j + 2])[0]
                     for j in range(i + 9, i + glen - 1, 2)]
            groups.append(('B', f3.decode('ascii', 'replace'), codes))
        elif _QTY_FIELD.match(f3):
            qty = int(f3.decode('ascii').strip()) if f3.strip().isdigit() else None
            if (glen - 9) % 2:
                return None
            codes = [struct.unpack('<H', tail[j:j + 2])[0]
                     for j in range(i + 9, i + glen - 1, 2)]
            groups.append(('A', qty, codes))
        else:
            return None
        i += glen
    return groups if i == len(tail) else None


def parse_tail_ext(tail):
    if not tail or len(tail) < 11:
        return None
    cands = []
    for s in (7 + tail[7], 9, 11, 13, 15):
        if s not in cands:
            cands.append(s)
    for s in cands:
        g = parse_chain_ext(tail, s)
        if g is not None:
            return g
    return None


def main():
    total = old_ok = ext_ok = 0
    changed = []
    still_fail = []
    for fn in sorted(os.listdir(PLMST_DIR)):
        cat = fn.replace('_PLMST.CD', '')
        data = open(os.path.join(PLMST_DIR, fn), 'rb').read()
        for fk, pn, nm, pr, tail in parse_plmst(data):
            total += 1
            old = parse_tail(tail)
            ext = parse_tail_ext(tail)
            if old is not None:
                old_ok += 1
                if ext is None:
                    changed.append((cat, fk, pn, 'ext lost a parsed record'))
                else:
                    old_simple = [(q, tuple(c)) for q, c in old]
                    ext_simple = [(q if kind == 'A' else None, tuple(c))
                                  for kind, q, c in ext]
                    if old_simple != ext_simple:
                        changed.append((cat, fk, pn, 'interpretation differs'))
            if ext is not None:
                ext_ok += 1
                for kind, q, c in ext:
                    if kind == 'B':
                        remarks[q] += 1
            else:
                still_fail.append((cat, fk, pn, len(tail), tail.hex()))
    print('total', total, 'old ok', old_ok, 'ext ok', ext_ok)
    print('changed interpretations', len(changed), changed[:5])
    print('still failing', len(still_fail))
    for r in still_fail[:10]:
        print(r)
    print('remark census', remarks.most_common(40))


if __name__ == '__main__':
    main()
