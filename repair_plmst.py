#!/usr/bin/env python3
"""Repair PLMST parse dropouts in epc_index.sqlite `parts`.

The original parse stopped at the first over-long record in some catalogs
(e.g. 11SE301: 173 of 14,333 records; 11SV401: 6). A plain u16LE length-chain
walk lands exactly on EOF for these files, so re-parse them fully with the
documented record layout and replace the catalog's rows — but only after the
extraction rule reproduces the already-indexed prefix exactly.
"""
import os, re, struct, sqlite3

BASE = '/home/hatch/workspace/epc-project'
con = sqlite3.connect(f'{BASE}/epc_index.sqlite')

def parse_file(path):
    data = open(path, 'rb').read()
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < 20 or off + ln > len(data):
            raise ValueError(f'chain break at {off} len={ln}')
        rec = data[off:off + ln]
        figkey = rec[2:12].decode('ascii', 'replace')
        partno = rec[12:24].decode('ascii', 'replace').strip().replace(' ', '')
        field = rec[24:82].decode('cp932', 'replace').strip()
        price = None
        name = field
        m = re.search(r'\s+(\d+)$', field)
        if m:
            price = int(m.group(1))
            name = field[:m.start()].rstrip()
        recs.append((figkey, partno, name, price, rec[82:]))
        off += ln
    assert off == len(data), f'chain ends at {off} != {len(data)}'
    return recs

files = sorted(os.listdir(f'{BASE}/cd/plmst_all'))
repaired, checked_ok, problems = [], [], []
for fn in files:
    cat = fn.replace('_PLMST.CD', '')
    try:
        recs = parse_file(f'{BASE}/cd/plmst_all/{fn}')
    except Exception as e:
        problems.append((cat, str(e)))
        continue
    old = con.execute('SELECT figkey, partno, name, price, tail FROM parts WHERE catalog=? ORDER BY rowid',
                      (cat,)).fetchall()
    old = [(o[0], o[1], o[2], o[3], bytes(o[4]) if o[4] is not None else b'') for o in old]
    if len(old) == len(recs) and old == recs:
        checked_ok.append(cat)
        continue
    # safety: the indexed rows must be an exact prefix of the full parse
    if recs[:len(old)] != old:
        problems.append((cat, f'prefix mismatch: indexed {len(old)} vs file {len(recs)}'))
        continue
    con.execute('DELETE FROM parts WHERE catalog=?', (cat,))
    con.executemany('INSERT INTO parts (catalog, figkey, partno, name, price, tail) VALUES (?,?,?,?,?,?)',
                    [(cat,) + r for r in recs])
    con.commit()
    repaired.append((cat, len(old), len(recs)))
    print(f'REPAIRED {cat}: {len(old)} -> {len(recs)} records', flush=True)

print(f'\nidentical (rule validated): {len(checked_ok)} catalogs')
print(f'repaired: {len(repaired)} catalogs, +{sum(n - o for _, o, n in repaired)} records')
for c, o, n in repaired: print(f'  {c}: {o} -> {n}')
print(f'problems: {problems}')
print('total parts now:', con.execute('SELECT COUNT(*) FROM parts').fetchone()[0])
con.close()
print('DONE')
