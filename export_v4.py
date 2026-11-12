#!/usr/bin/env python3
"""Export the v4 app DB (epc_v4.db) from epc_index.sqlite — all 82 catalogs.
Schema is normalized around blocks.blkid to keep size down:
  parts / hotspots reference blkid instead of repeating catalog/block/figure/sub.
No indexes on partno/name_norm: the app searches with LIKE '%q%' (full scan
either way), so those indexes would be pure overhead (~tens of MB)."""
import sqlite3, unicodedata, os

BASE = '/home/hatch/workspace/epc-project'
src = sqlite3.connect(f'{BASE}/epc_index.sqlite')
out_path = f'{BASE}/android/assets/epc_v4.db'
if os.path.exists(out_path): os.remove(out_path)
dst = sqlite3.connect(out_path)
dst.execute('PRAGMA page_size=4096')

def nfkc(s):
    return unicodedata.normalize('NFKC', s) if s else s

dst.executescript('''
CREATE TABLE catalogs(catalog TEXT PRIMARY KEY, label TEXT);
CREATE TABLE models(catalog TEXT, name TEXT, type_full TEXT, type_code TEXT,
                    grade TEXT, trans TEXT, engine TEXT, serial_from TEXT, serial_to TEXT,
                    ids TEXT);
CREATE TABLE groups(catalog TEXT, seq INT, gno TEXT, name TEXT, code TEXT);
CREATE TABLE block_groups(catalog TEXT, block TEXT, group_seq INT, fig_from INT, fig_to INT);
CREATE TABLE blocks(blkid INTEGER PRIMARY KEY, catalog TEXT, block TEXT, figure TEXT, sub TEXT,
                    title TEXT, drawcode TEXT, png TEXT, width INT, height INT);
CREATE TABLE parts(id INTEGER PRIMARY KEY, blkid INT, item TEXT, partno TEXT, name_norm TEXT,
                   price INT, qty INT, gjson TEXT);
-- NOTE: no separate codes column — it is exactly the union of gjson's group
-- code lists (set-verified over all rows); MainActivity rebuilds it per row.
-- Dropping it saved ~40 MB (159,956,992 -> 118,370,304 bytes).
CREATE TABLE hotspots(blkid INT, item TEXT, x1 INT, y1 INT, x2 INT, y2 INT);
CREATE TABLE equip(id INTEGER PRIMARY KEY, name TEXT);
''')
for eid, ename in src.execute('SELECT id, name FROM equip ORDER BY id'):
    dst.execute('INSERT INTO equip VALUES (?,?)', (eid, ename))
dst.commit()

CATS = [r[0] for r in src.execute('SELECT DISTINCT catalog FROM parts2 ORDER BY catalog')]
blkid_of = {}
next_blk = 1

for cat in CATS:
    labels = [' '.join(x) for x in src.execute(
        'SELECT DISTINCT name, type_full FROM models WHERE catalog=? ORDER BY name, type_full', (cat,))]
    dst.execute('INSERT INTO catalogs VALUES (?,?)', (cat, ' / '.join(labels)))
    for r in src.execute('SELECT name, type_full, type_code, grade, trans, engine, serial_from, serial_to, ids '
                         'FROM models WHERE catalog=? ORDER BY name, type_full, grade, trans, serial_from', (cat,)):
        r = (nfkc(r[0]), r[1], r[2], nfkc(r[3])) + r[4:]
        dst.execute('INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?,?)', (cat,) + r)
    for seq, gno, name, code in src.execute('SELECT seq, gno, name, code FROM groups WHERE catalog=? ORDER BY seq', (cat,)):
        dst.execute('INSERT INTO groups VALUES (?,?,?,?,?)', (cat, seq, gno, nfkc(name), code))
    for block, gseq, ff, ft in src.execute('SELECT block, group_seq, fig_from, fig_to FROM block_groups WHERE catalog=?', (cat,)):
        dst.execute('INSERT INTO block_groups VALUES (?,?,?,?,?)', (cat, block, gseq, ff, ft))

    # blocks = figure_map variants (with png) UNION blocks-table variants UNION parts2 variants
    blk_meta = {}   # (block, figure, sub) -> (title, drawcode)
    for block, fig, sub, title, code in src.execute(
            'SELECT block, figure, sub, title, drawcode FROM blocks WHERE catalog=?', (cat,)):
        blk_meta[(block, fig, sub)] = (title, code)
    variants = {}
    for block, fig, sub, png, w, h in src.execute(
            '''SELECT fm.block, fm.figure, fm.sub, fm.png, f.width, f.height
               FROM figure_map fm JOIN figures f ON f.catalog=fm.catalog AND f.png=fm.png
               WHERE fm.catalog=?''', (cat,)):
        variants[(block, fig, sub)] = (png, w, h)
    for key in blk_meta:
        variants.setdefault(key, (None, None, None))
    for block, fig, sub in src.execute(
            'SELECT DISTINCT block, figure, sub FROM parts2 WHERE catalog=?', (cat,)):
        variants.setdefault((block, fig, sub), (None, None, None))
    for (block, fig, sub), (png, w, h) in sorted(variants.items()):
        title, code = blk_meta.get((block, fig, sub), (None, None))
        dst.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (next_blk, cat, block, fig, sub, nfkc(title), code, png, w, h))
        blkid_of[(cat, block, fig, sub)] = next_blk
        next_blk += 1
dst.commit()
print("blocks:", next_blk - 1)

# parts (global; id = parts2 rowid, stable cart key)
nparts = 0
for rowid, cat, block, fig, sub, item, partno, name, price, qty, codes, gjson in src.execute(
        'SELECT rowid, catalog, block, figure, sub, item, partno, name, price, qty, codes, gjson FROM parts2 ORDER BY rowid'):
    dst.execute('INSERT INTO parts VALUES (?,?,?,?,?,?,?,?)',
                (rowid, blkid_of[(cat, block, fig, sub)], item, partno, nfkc(name), price, qty, gjson))
    nparts += 1
dst.commit()
print("parts:", nparts)

# hotspots via figure_map -> figures -> hotspots, keyed by blkid
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
print("hotspots:", nhs)

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
for t in ['catalogs', 'models', 'groups', 'block_groups', 'blocks', 'parts', 'hotspots']:
    print(t, dst.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
print('parts with codes (in src parts2):', src.execute("SELECT COUNT(*) FROM parts2 WHERE codes <> ''").fetchone()[0])
print('blocks with png:', dst.execute("SELECT COUNT(*) FROM blocks WHERE png IS NOT NULL").fetchone()[0])
dst.close()
print('size:', os.path.getsize(out_path))
src.close()
