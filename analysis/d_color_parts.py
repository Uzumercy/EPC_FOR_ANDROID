#!/usr/bin/env python3
"""D班 項目3: PLMST の色部品（名前に *色コード* を含む）の実態と IBHTBL の突合。
- 色コード付き部品名のサンプル
- 名前中のコード集合 vs IBHTBL 第2節キー
- 第1節文字集合の字母 vs 各種候補（色コード構成文字など）
"""
import os
import re
import struct
import sys
from collections import Counter, defaultdict

BASE = os.path.expanduser('~/workspace/epc-project')
sys.path.insert(0, os.path.join(BASE, 'analysis'))
sys.path.insert(0, os.path.join(BASE, 'converter'))
import iso_index  # noqa: E402
from epcconv.parsers import parse_plmst  # noqa: E402

iso = iso_index.open_iso()


def parse_ibhtbl(data):
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        key = rec[2:12].decode('ascii', 'replace').strip()
        chars = rec[14:].decode('ascii', 'replace')
        recs.append((key, chars))
        off += ln
    return recs


for cat in ['11SA702', '11S0601']:
    print(f'===== {cat}')
    pdata = open(os.path.join(BASE, 'cd/plmst_all', f'{cat}_PLMST.CD'), 'rb').read()
    codes_in_names = Counter()
    samples = []
    for (_fk, pn, name, _pr, _t) in parse_plmst(pdata):
        for m in re.findall(r'\*([^*]+)\*', name):
            codes_in_names[m] += 1
            if len(samples) < 12:
                samples.append((pn, name))
    print(' 名前中の *...* コード上位:', codes_in_names.most_common(25))
    for pn, nm in samples[:8]:
        print(f'   {pn} {nm}')
    ibh = parse_ibhtbl(iso_index.get(iso, f'/{cat}/IBHTBL.CD'))
    s1 = [c for k, c in ibh if not k]
    s2 = [(k, c) for k, c in ibh if k]
    print(f' IBHTBL: 第1節 {len(s1)}件, 第2節 {len(s2)}件')
    print('  第2節キー:', [k for k, _ in s2])
    # 名前中コードと第2節キーの一致率
    name_codes = set(codes_in_names)
    s2keys = {k for k, _ in s2}
    print(f'  名前中コード {len(name_codes)}種 / 第2節キー {len(s2keys)}種 / 共通 {len(name_codes & s2keys)}')
    only_name = sorted(name_codes - s2keys)
    print('  名前のみ:', only_name[:20])
iso.close()
