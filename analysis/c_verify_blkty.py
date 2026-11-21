#!/usr/bin/env python3
"""Verify BLKTYTBL tail structure across all 82 catalogs.

Hypothesis: record = [u16 len][figkey 7B][drawcode 10B][title 50B]
  [u32LE plmst_offset][u32LE plmst_length]
  [u32LE kc_offset][u32LE kc_length]
  [u16LE model-ID codes ...]
where plmst_offset/length delimit the figure's segment in PLMST.CD and
kc_offset/length delimit a segment in KCMST.CD.  The code list is compared
with the union of PLMST tail group codes of the figure's parts.
"""
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.expanduser('~/workspace/epc-project/converter'))
from epcconv.parsers import parse_plmst, parse_figkey, parse_tail  # noqa: E402

BASE = os.path.expanduser('~/workspace/epc-project')
WORK = os.path.join(BASE, 'analysis/work')
PLMST_DIR = os.path.join(BASE, 'cd/plmst_all')
EXTRACTED = os.path.join(BASE, 'cd/extracted')


def parse_blkty(data):
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < 85 or off + ln > len(data):
            raise ValueError(f'BLKTYTBL chain break at {off} len={ln}')
        recs.append(data[off:off + ln])
        off += ln
    return recs


def main():
    stats = Counter()
    problems = []
    code_cmp = Counter()
    for cat in sorted(os.listdir(WORK)):
        bdata = open(os.path.join(WORK, cat, 'BLKTYTBL.CD'), 'rb').read()
        pdata = open(os.path.join(PLMST_DIR, f'{cat}_PLMST.CD'), 'rb').read()
        recs = parse_blkty(bdata)
        parts = parse_plmst(pdata)
        # PLMST figure segments
        offs = []
        o = 0
        while o < len(pdata):
            ln = struct.unpack_from('<H', pdata, o)[0]
            offs.append(o)
            o += ln
        fig_seg = {}
        fig_codes = {}
        for (fk, pn, nm, pr, tail), po in zip(parts, offs):
            k = parse_figkey(fk)[:3]
            ln = struct.unpack_from('<H', pdata, po)[0]
            if k not in fig_seg:
                fig_seg[k] = [po, 0]
            fig_seg[k][1] = po + ln - fig_seg[k][0]
            g = parse_tail(tail)
            if g:
                s = fig_codes.setdefault(k, set())
                for qty, codes in g:
                    s.update(codes)
        # KCMST only extracted for 11SA702; size check there, chain elsewhere
        kcdata = None
        kcpath = os.path.join(EXTRACTED, cat, 'KCMST.CD')
        if os.path.exists(kcpath):
            kcdata = open(kcpath, 'rb').read()
        prev_end_p = 0
        prev_end_k = 0
        for r in recs:
            fk = r[2:9].decode('ascii', 'replace')
            k = (fk[0:3].strip(), fk[3:5].strip(), fk[5:7].strip())
            po, pl, ko, kl = struct.unpack_from('<IIII', r, 69)
            codes = [struct.unpack_from('<H', r, j)[0]
                     for j in range(85, len(r) - 1, 2)]
            stats['records'] += 1
            if fig_seg.get(k) != [po, pl]:
                problems.append((cat, k, 'PLMST seg mismatch',
                                 fig_seg.get(k), (po, pl)))
            if po != prev_end_p:
                problems.append((cat, k, 'PLMST offsets not contiguous', po, prev_end_p))
            if ko != prev_end_k:
                problems.append((cat, k, 'KC offsets not contiguous', ko, prev_end_k))
            prev_end_p = po + pl
            prev_end_k = ko + kl
            if kcdata is not None and ko + kl > len(kcdata):
                problems.append((cat, k, 'KC seg beyond KCMST size'))
            # code list comparison
            ucodes = fig_codes.get(k, set())
            if set(codes) == ucodes:
                code_cmp['set_equal_union'] += 1
            elif set(codes) > ucodes:
                code_cmp['superset_of_union'] += 1
            elif set(codes) < ucodes:
                code_cmp['subset_of_union'] += 1
            else:
                code_cmp['partial_overlap'] += 1
            if codes == sorted(codes):
                code_cmp['sorted_ascending'] += 1
            stats['code_list_total'] += 1
        if prev_end_p != len(pdata):
            problems.append((cat, 'END', 'PLMST segs do not cover file', prev_end_p, len(pdata)))
        if kcdata is not None:
            stats['kc_end'] = prev_end_k
            stats['kc_size'] = len(kcdata)
            stats['kc_cover_match'] = int(prev_end_k == len(kcdata))
    print(dict(stats))
    print('code comparison:', dict(code_cmp))
    print('problems:', len(problems))
    for p in problems[:20]:
        print(p)


if __name__ == '__main__':
    main()
