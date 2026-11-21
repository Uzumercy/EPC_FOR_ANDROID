#!/usr/bin/env python3
"""Verify PLMKSBI1/2 and PLMSBBI1/2 structure against PLMST for all 82 catalogs.

Hypotheses under test:
- *BI1: fixed 10-byte records [2-byte bucket key][u32LE byte offset into BI2]
  [u32LE byte length]; offsets are cumulative and lengths sum to BI2 size.
- PLMSBBI2: chain of [u16LE len][5-byte main partno][n * (u32LE PLMST offset,
  u16LE PLMST record length)]; (len-7) % 6 == 0.
- PLMKSBI2: chain of [u16LE len][10-byte name prefix (PLMST name bytes 25:35)]
  [n * (u32LE PLMST offset, u16LE PLMST record length)]; (len-12) % 6 == 0.
- Every PLMST record is referenced exactly once by each index.
"""
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.expanduser('~/workspace/epc-project/converter'))
from epcconv.parsers import parse_plmst  # noqa: E402

BASE = os.path.expanduser('~/workspace/epc-project')
WORK = os.path.join(BASE, 'analysis/work')
PLMST_DIR = os.path.join(BASE, 'cd/plmst_all')


def plmst_offsets(data):
    offs = []
    off = 0
    while off < len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        offs.append((off, ln))
        off += ln
    assert off == len(data)
    return offs


def parse_bi1(data):
    assert len(data) % 10 == 0, f'BI1 size {len(data)} not multiple of 10'
    out = []
    for i in range(0, len(data), 10):
        key = data[i:i + 2]
        off, ln = struct.unpack_from('<II', data, i + 2)
        out.append((key, off, ln))
    return out


def check_bucket_chain(buckets, body_size):
    pos = 0
    for key, off, ln in buckets:
        if off != pos:
            return f'bucket {key} offset {off} != cumulative {pos}'
        pos += ln
    if pos != body_size:
        return f'bucket lengths sum {pos} != body size {body_size}'
    return None


def parse_bi2(data, keylen):
    """Yield (key, [(off, ln), ...]) per record; strict chain."""
    out = []
    off = 0
    hdr = 2 + keylen
    while off < len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < hdr or (ln - hdr) % 6 or off + ln > len(data):
            raise ValueError(f'BI2 chain break at {off} len={ln}')
        rec = data[off:off + ln]
        ents = [struct.unpack_from('<IH', rec, hdr + 6 * i)
                for i in range((ln - hdr) // 6)]
        out.append((rec[2:2 + keylen], ents))
        off += ln
    return out


def main():
    cats = sorted(os.listdir(WORK))
    grand = Counter()
    problems = []
    for cat in cats:
        pdata = open(os.path.join(PLMST_DIR, f'{cat}_PLMST.CD'), 'rb').read()
        recs = parse_plmst(pdata)
        offs = plmst_offsets(pdata)
        offmap = dict(offs)
        namekey = {}
        pnkey = {}
        for (o, l), r, raw_off in zip(offs, recs, [o for o, _ in offs]):
            raw = pdata[raw_off:raw_off + l]
            namekey[o] = raw[25:35]
            pnkey[o] = r[1][:5].encode('ascii', 'replace')
        for kind, keylen, keyfn in (('PLMSBBI', 5, pnkey), ('PLMKSBI', 10, namekey)):
            b1 = parse_bi1(open(os.path.join(WORK, cat, f'{kind}1.CD'), 'rb').read())
            b2data = open(os.path.join(WORK, cat, f'{kind}2.CD'), 'rb').read()
            err = check_bucket_chain(b1, len(b2data))
            if err:
                problems.append((cat, kind, err))
                continue
            # bucket key must equal first 2 bytes of the record keys it covers
            try:
                b2 = parse_bi2(b2data, keylen)
            except ValueError as e:
                problems.append((cat, kind, str(e)))
                continue
            seen = Counter()
            pos = 0
            bidx = 0
            for key, ents in b2:
                reclen = 2 + keylen + 6 * len(ents)
                while bidx < len(b1) and b1[bidx][1] + b1[bidx][2] <= pos:
                    bidx += 1
                if bidx >= len(b1) or not (b1[bidx][1] <= pos < b1[bidx][1] + b1[bidx][2]):
                    problems.append((cat, kind, f'record at {pos} outside buckets'))
                elif key[:2] != b1[bidx][0]:
                    problems.append((cat, kind,
                                     f'bucket key {b1[bidx][0]} != record key head {key[:2]} at {pos}'))
                for o, l in ents:
                    seen[o] += 1
                    if o not in offmap:
                        problems.append((cat, kind, f'entry offset {o} not a PLMST offset'))
                    elif offmap[o] != l:
                        problems.append((cat, kind, f'entry len {l} != PLMST len {offmap[o]} at {o}'))
                    elif keyfn[o] != key:
                        problems.append((cat, kind, f'key mismatch at off {o}: {key} vs {keyfn[o]}'))
                pos += reclen
            # coverage: each PLMST record exactly once
            want = Counter({o: 1 for o, _ in offs})
            if seen != want:
                missing = sum((want - seen).values())
                extra = sum((seen - want).values())
                problems.append((cat, kind,
                                 f'coverage mismatch missing={missing} dup/extra={extra}'))
            grand[f'{kind}_records'] += len(b2)
            grand[f'{kind}_entries'] += sum(len(e) for _, e in b2)
            grand[f'{kind}_buckets'] += len(b1)
        grand['catalogs'] += 1
        grand['plmst_records'] += len(recs)
    print(dict(grand))
    print('problems:', len(problems))
    for p in problems[:40]:
        print(p)


if __name__ == '__main__':
    main()
