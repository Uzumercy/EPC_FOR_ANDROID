#!/usr/bin/env python3
"""Identify NSX catalogs from the 10Z model master and locate their data."""
import io
import os
import sys
from collections import defaultdict

BASE = os.path.expanduser('~/workspace/epc-project')
sys.path.insert(0, os.path.join(BASE, 'converter'))
from epcconv.parsers import parse_ksrbhmh  # noqa: E402
import pycdlib  # noqa: E402

ISOS = {
    '10Z': os.path.join(BASE, 'cd2/21CD10Z.iso'),
    '08X': os.path.join(BASE, 'cd2/21CD08X.iso'),
    'DISC1': os.path.join(BASE, 'cd/HONDA_EPC.ISO'),
}
PRIORITY = ['10Z', '08X', 'DISC1']  # newest first

# ---- 1. NSX models in the 10Z master -----------------------------------
models = parse_ksrbhmh(os.path.join(BASE, 'cd2/work/KSRBHMH_DISC2_21CD10Z.CD'))
print(f'10Z master: {len(models)} models')
nsx = [m for m in models if 'NSX' in m['name'].upper()]
print(f'NSX models: {len(nsx)}')
by_cat = defaultdict(list)
for m in nsx:
    by_cat[m['catalog']].append(m)
for cat in sorted(by_cat):
    ms = by_cat[cat]
    names = sorted({m['name'] for m in ms})
    types = sorted({m['type_full'] for m in ms})
    engines = sorted({m['engine'] for m in ms})
    print(f'  catalog {cat}: {len(ms)} models, names={names}, '
          f'types={types[:8]}, engines={engines}')

# ---- 2. which discs carry each catalog (PLMST.CD present) --------------
owners = {}
for tag in PRIORITY:
    iso = pycdlib.PyCdlib()
    iso.open(ISOS[tag])
    cats = set()
    for dirname, dirlist, filelist in iso.walk(iso_path='/'):
        parts = [p for p in dirname.split('/') if p]
        if len(parts) == 1:
            names = {f.split(';')[0].upper() for f in filelist}
            if 'PLMST.CD' in names:
                cats.add(parts[0])
    iso.close()
    owners[tag] = cats
    print(f'{tag}: {len(cats)} catalogs with PLMST')

print('\nNSX catalog ownership (newest wins):')
for cat in sorted(by_cat):
    have = [t for t in PRIORITY if cat in owners[t]]
    print(f'  {cat}: present on {have} -> adopt {have[0] if have else "NONE!"}')
