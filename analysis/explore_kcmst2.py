#!/usr/bin/env python3
"""B班 探索3: KCMST 全件分解、注記一覧、PLMST品名との一致率"""
import struct, re, collections, sqlite3, os, unicodedata

BASE = os.path.expanduser('~/workspace/epc-project/cd/extracted/11SA702/')
d = open(BASE + 'KCMST.CD', 'rb').read()
off = 0; recs = []
while off < len(d):
    ln = struct.unpack_from('<H', d, off)[0]
    recs.append(d[off:off+ln]); off += ln
assert off == len(d)

entries = []
notes = collections.Counter()
badval = []
for r in recs:
    name = r[2:52].decode('cp932', errors='replace').strip()
    valraw = r[52:57].decode('ascii', errors='replace').strip()
    entries.append((name, valraw))
    if not re.fullmatch(r'\d+\.\d+', valraw or ''):
        badval.append((name, valraw, len(r)))
    # 継続ブロック (57バイト目以降、60B単位)
    rest = r[57:]
    assert len(rest) % 60 == 0, (len(r), len(rest))
    for i in range(0, len(rest), 60):
        blk = rest[i:i+60].decode('cp932', errors='replace').strip()
        notes[blk] += 1

print('entries:', len(entries))
print('bad first-block values:', badval[:10], 'count', len(badval))
print()
print('distinct note blocks:', len(notes))
for n, c in notes.most_common():
    print(f'  x{c}: {n!r}')

names = [n for n, v in entries]
print()
print('names sorted by cp932 bytes:', names == sorted(names, key=lambda s: s.encode('cp932', errors='replace')))
print('names unique:', len(set(names)), 'dup names:', [k for k, c in collections.Counter(names).items() if c > 1][:10])

# PLMST (11SA702) の品名と比較
db = sqlite3.connect(os.path.expanduser('~/workspace/epc-project/epc_index.sqlite'))
plmst = db.execute("SELECT DISTINCT name FROM parts WHERE catalog='11SA702'").fetchall()
plmst_names = set()
for (n,) in plmst:
    plmst_names.add(unicodedata.normalize('NFKC', n).strip())
print()
print('PLMST distinct names (NFKC):', len(plmst_names))
kc = set(unicodedata.normalize('NFKC', n).strip() for n in names)
print('KCMST names in PLMST:', len(kc & plmst_names), '/', len(kc),
      f"= {len(kc & plmst_names)/len(kc)*100:.1f}%")
print('PLMST names covered by KCMST:', len(kc & plmst_names), '/', len(plmst_names),
      f"= {len(kc & plmst_names)/len(plmst_names)*100:.1f}%")
print()
print('KCMST names NOT in PLMST (first 20):')
for n in sorted(kc - plmst_names)[:20]:
    print('  ', n)
print('PLMST names NOT in KCMST (first 20):')
for n in sorted(plmst_names - kc)[:20]:
    print('  ', n)

# 値の分布 (全件, 第1ブロック)
vals = [float(v) for n, v in entries if re.fullmatch(r'\d+\.\d+', v or '')]
print()
print('values: n=', len(vals), 'min', min(vals), 'max', max(vals))
hist = collections.Counter()
for v in vals:
    hist[round(v)] += 1
print('integer-part histogram:', sorted(hist.items()))
big = [(n, v) for n, v in entries if re.fullmatch(r'\d+\.\d+', v or '') and float(v) >= 4.0]
print('entries with value>=4.0:', len(big))
for n, v in big[:25]:
    print('   ', v, n)
