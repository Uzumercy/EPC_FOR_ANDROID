#!/usr/bin/env python3
"""Extract GRPTBL/BLKTBL/BLKTYTBL for all catalogs from the ISO + recon stats."""
import io, os, struct, sqlite3
import pycdlib

BASE = '/home/hatch/workspace/epc-project'
WANT = {'GRPTBL.CD', 'BLKTBL.CD', 'BLKTYTBL.CD'}
con = sqlite3.connect(f'{BASE}/epc_index.sqlite')
cats = [r[0] for r in con.execute('SELECT DISTINCT catalog FROM figures ORDER BY catalog')]
con.close()
print("catalogs:", len(cats))

iso = pycdlib.PyCdlib(); iso.open(f'{BASE}/cd/HONDA_EPC.ISO')
# map: catalog -> {filename: iso_path}
found = {}
for dirpath, dirnames, filenames in iso.walk(iso_path='/'):
    parts = [p for p in dirpath.split('/') if p]
    if len(parts) != 1: continue
    cat = parts[0]
    if cat not in cats: continue
    for fn in filenames:
        name = fn.split(';')[0]
        if name in WANT:
            found.setdefault(cat, {})[name] = dirpath.rstrip('/') + '/' + fn
missing = []
for cat in cats:
    d = f'{BASE}/cd/extracted/{cat}'
    os.makedirs(d, exist_ok=True)
    for name in WANT:
        out = os.path.join(d, name)
        if os.path.exists(out): continue
        ip = found.get(cat, {}).get(name)
        if ip is None:
            missing.append((cat, name)); continue
        buf = io.BytesIO()
        iso.get_file_from_iso_fp(buf, iso_path=ip)
        with open(out, 'wb') as f: f.write(buf.getvalue())
iso.close()
print("missing files:", missing)

# recon: BLKTYTBL record length stats + title strictness check
import collections
for cat in cats:
    p = f'{BASE}/cd/extracted/{cat}/BLKTYTBL.CD'
    if not os.path.exists(p): continue
    data = open(p, 'rb').read()
    lens = collections.Counter()
    off = 0; strict_ok = 0; nrec = 0
    while off + 2 <= len(data):
        ln = struct.unpack('<H', data[off:off+2])[0]
        if ln < 20 or off + ln > len(data): break
        rec = data[off:off+ln]
        lens[ln] += 1; nrec += 1
        if ln >= 69:
            try:
                t = rec[19:69].decode('cp932')
                if all(ord(c) >= 0x20 or c in ' ' for c in t): strict_ok += 1
            except UnicodeDecodeError:
                pass
        off += ln
    consumed = off / len(data) if data else 0
    print(f"{cat}: recs={nrec} lens={dict(lens)} chain={consumed:.2f} fixed50strict={strict_ok}/{nrec} grp={os.path.getsize(f'{BASE}/cd/extracted/{cat}/GRPTBL.CD') if os.path.exists(f'{BASE}/cd/extracted/{cat}/GRPTBL.CD') else '-'} blk={os.path.getsize(f'{BASE}/cd/extracted/{cat}/BLKTBL.CD') if os.path.exists(f'{BASE}/cd/extracted/{cat}/BLKTBL.CD') else '-'}")
