#!/usr/bin/env python3
"""B班 探索2: KCMST.CD (11SA702) の構造・分布・PLMST品名との対応"""
import struct, re, collections, unicodedata, os

BASE = os.path.expanduser('~/workspace/epc-project/cd/extracted/11SA702/')
d = open(BASE + 'KCMST.CD', 'rb').read()

# 可変長チェーン
off = 0; recs = []
while off < len(d):
    ln = struct.unpack_from('<H', d, off)[0]
    if ln < 2 or off + ln > len(d):
        print('CHAIN FAIL at', off); break
    recs.append(d[off:off+ln]); off += ln
print('file size', len(d), 'records', len(recs), 'chain end', off, 'OK' if off == len(d) else 'FAIL')
print('record lengths:', collections.Counter(len(r) for r in recs))

# レコード内訳の推定: [len2][name 50B?][number ascii right-aligned]
for i, r in enumerate(recs[:6]):
    print(i, len(r), repr(r))
print('...')
for i, r in enumerate(recs[-3:]):
    print(len(recs)-3+i, len(r), repr(r))

# 長さ57のレコード: 末尾の数値フィールド位置を確認
r = recs[0]
print()
print('rec0 bytes:', r)
# 数値を正規表現で末尾から取る
pat = re.compile(rb'(\d+\.\d+)\s*$')
vals = []
bad = 0
for r in recs:
    m = pat.search(r.rstrip())
    if m:
        vals.append(float(m.group(1)))
    else:
        bad += 1
        if bad <= 5:
            print('NO NUMBER:', repr(r))
print('numeric records:', len(vals), 'no-number:', bad)
print('value stats: min', min(vals), 'max', max(vals))
c = collections.Counter(vals)
print('distinct values:', len(c))
print('top20 values:', c.most_common(20))
# 小数部分布
frac = collections.Counter(round(v - int(v), 2) for v in vals)
print('fractional parts:', sorted(frac.items())[:30])
