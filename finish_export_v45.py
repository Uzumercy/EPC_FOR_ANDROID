#!/usr/bin/env python3
"""Finish the v4.5 app-DB export: the background export_v4.py run was
reaped after the parts commit, leaving hotspots empty and indexes/VACUUM
undone. This replicates exactly the tail of export_v4.py (hotspots via
figure_map -> figures -> hotspots keyed by blkid, then indexes + VACUUM)
against the already-exported android/assets/epc_v4.db."""
import sqlite3, os

BASE = '/home/hatch/workspace/epc-project'
src = sqlite3.connect(f'{BASE}/epc_index.sqlite')
dst = sqlite3.connect(f'{BASE}/android/assets/epc_v4.db')

blkid_of = {}
for blkid, cat, block, fig, sub in dst.execute('SELECT blkid, catalog, block, figure, sub FROM blocks'):
    blkid_of[(cat, block, fig, sub)] = blkid
print('blocks in app db:', len(blkid_of))

dst.execute('DELETE FROM hotspots')
nhs = 0
for cat, block, fig, sub, png in src.execute('SELECT catalog, block, figure, sub, png FROM figure_map'):
    bk = blkid_of.get((cat, block, fig, sub))
    if bk is None: continue
    subdir, filename = src.execute('SELECT subdir, filename FROM figures WHERE catalog=? AND png=?', (cat, png)).fetchone()
    for item, x1, y1, x2, y2 in src.execute(
            'SELECT item, x1, y1, x2, y2 FROM hotspots WHERE catalog=? AND subdir=? AND filename=?',
            (cat, subdir, filename)):
        dst.execute('INSERT INTO hotspots VALUES (?,?,?,?,?,?)', (bk, item, x1, y1, x2, y2))
        nhs += 1
dst.commit()
print('hotspots:', nhs)

dst.executescript('''
CREATE INDEX idx_parts_blk ON parts(blkid);
CREATE INDEX idx_hs_blk ON hotspots(blkid);
CREATE INDEX idx_blocks_cat ON blocks(catalog, block, figure, sub);
CREATE INDEX idx_models_cat ON models(catalog);
CREATE INDEX idx_groups_cat ON groups(catalog);
CREATE INDEX idx_bg_cat ON block_groups(catalog, block);
''')
dst.commit()
dst.execute('VACUUM')
dst.commit()
for t in ['catalogs', 'models', 'groups', 'block_groups', 'blocks', 'parts', 'hotspots', 'equip']:
    print(t, dst.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
print('blocks with png:', dst.execute('SELECT COUNT(*) FROM blocks WHERE png IS NOT NULL').fetchone()[0])
dst.close()
print('size:', os.path.getsize(f'{BASE}/android/assets/epc_v4.db'))
src.close()
print('DONE')
