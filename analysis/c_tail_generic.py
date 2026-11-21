#!/usr/bin/env python3
"""Generic-field variant of the PLMST tail grammar.

Group = [u16LE len][4 bytes][3-byte field][u16LE codes...].
The 3-byte field is classified as:
  A: quantity field matching _QTY_FIELD ('  1', ' 16', '  N', ...)
  B: remark field containing '(' or ')' ('(1)', '(14', '12)', '(N)')
  X: any other 3-byte field ('   ', 'Y01', 'E01', ' L1', ' N ', ...)
Codes always start at group+9; (len-9) must be even.
Verify: total successes, and identical interpretation for all records
the current production parser already handles.
"""
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.expanduser('~/workspace/epc-project/converter'))
from epcconv.parsers import parse_plmst, parse_tail, _QTY_FIELD  # noqa: E402

BASE = os.path.expanduser('~/workspace/epc-project')
PLMST_DIR = os.path.join(BASE, 'cd/plmst_all')
xfields = Counter()


def parse_chain_gen(tail, start):
    groups = []
    i = start
    while i < len(tail):
        if i + 9 > len(tail):
            return None
        glen = struct.unpack('<H', tail[i:i + 2])[0]
        if glen < 9 or i + glen > len(tail) or (glen - 9) % 2:
            return None
        f3 = tail[i + 6:i + 9]
        codes = [struct.unpack('<H', tail[j:j + 2])[0]
                 for j in range(i + 9, i + glen - 1, 2)]
        if _QTY_FIELD.match(f3):
            qty = int(f3.decode('ascii').strip()) if f3.strip().isdigit() else None
            groups.append(('A', qty, codes))
        elif b'(' in f3 or b')' in f3:
            groups.append(('B', f3.decode('ascii', 'replace'), codes))
        else:
            groups.append(('X', f3.decode('ascii', 'replace'), codes))
        i += glen
    return groups if i == len(tail) else None


def parse_tail_gen(tail):
    if not tail or len(tail) < 11:
        return None
    cands = []
    for s in (7 + tail[7], 9, 11, 13, 15):
        if s not in cands:
            cands.append(s)
    for s in cands:
        g = parse_chain_gen(tail, s)
        if g is not None:
            return g
    return None


def main():
    total = old_ok = gen_ok = 0
    changed = []
    still = []
    for fn in sorted(os.listdir(PLMST_DIR)):
        cat = fn.replace('_PLMST.CD', '')
        data = open(os.path.join(PLMST_DIR, fn), 'rb').read()
        for fk, pn, nm, pr, tail in parse_plmst(data):
            total += 1
            old = parse_tail(tail)
            gen = parse_tail_gen(tail)
            if old is not None:
                old_ok += 1
                if gen is None:
                    changed.append((cat, fk, pn, 'lost'))
                else:
                    o = [(q, tuple(c)) for q, c in old]
                    g = [(q if kind == 'A' else None, tuple(c))
                         for kind, q, c in gen]
                    if o != g:
                        changed.append((cat, fk, pn, 'differs'))
            if gen is not None:
                gen_ok += 1
                for kind, q, c in gen:
                    if kind == 'X':
                        xfields[q] += 1
            else:
                still.append((cat, fk, pn, tail.hex()))
    print('total', total, 'old ok', old_ok, 'generic ok', gen_ok)
    print('changed', len(changed), changed[:5])
    print('still failing', len(still))
    for s in still:
        print(s)
    print('X-field census', xfields.most_common(30))


if __name__ == '__main__':
    main()
