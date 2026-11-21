#!/usr/bin/env python3
"""Extract C-team target files for all 82 catalogs from the DISC1 ISO."""
import os
import pycdlib

ISO = os.path.expanduser('~/workspace/epc-project/cd/HONDA_EPC.ISO')
OUT = os.path.expanduser('~/workspace/epc-project/analysis/work')
TARGETS = ('PLMKSBI1.CD', 'PLMKSBI2.CD', 'PLMSBBI1.CD', 'PLMSBBI2.CD',
           'BLKTYTBL.CD')

iso = pycdlib.PyCdlib()
iso.open(ISO)
catalogs = []
for dirname, dirlist, filelist in iso.walk(iso_path='/'):
    if dirname == '/':
        catalogs = sorted(dirlist)
        break
print('catalogs', len(catalogs))
missing = []
for cat in catalogs:
    cdir = os.path.join(OUT, cat)
    os.makedirs(cdir, exist_ok=True)
    for t in TARGETS:
        dst = os.path.join(cdir, t)
        if os.path.exists(dst):
            continue
        try:
            with open(dst, 'wb') as f:
                iso.get_file_from_iso_fp(f, iso_path=f'/{cat}/{t}')
        except Exception as e:
            missing.append((cat, t, str(e)))
print('missing', missing)
iso.close()
