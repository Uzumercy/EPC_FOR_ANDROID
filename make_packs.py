#!/usr/bin/env python3
"""Build per-catalog image packs: packs/<catalog>.zip with entries named
exactly as figures.png (e.g. '11SA702/1/SA71E010.2.png'), ZIP_STORED."""
import os, sqlite3, zipfile

BASE = '/home/hatch/workspace/epc-project'
os.makedirs(f'{BASE}/packs', exist_ok=True)
con = sqlite3.connect(f'{BASE}/epc_index.sqlite')
cats = [r[0] for r in con.execute('SELECT DISTINCT catalog FROM figures ORDER BY catalog')]
total = 0
for cat in cats:
    pngs = [r[0] for r in con.execute('SELECT png FROM figures WHERE catalog=? ORDER BY png', (cat,))]
    out = f'{BASE}/packs/{cat}.zip'
    tmp = out + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
        for png in pngs:
            z.write(os.path.join(BASE, 'figures', png), arcname=png)
    os.replace(tmp, out)
    sz = os.path.getsize(out)
    total += sz
    print(f"{cat}: {len(pngs)} files, {sz/1e6:.1f} MB", flush=True)
con.close()
print(f"packs total: {total/1e6:.1f} MB across {len(cats)} catalogs")
print("DONE")
