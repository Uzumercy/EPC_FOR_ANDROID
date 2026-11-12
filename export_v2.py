#!/usr/bin/env python3
"""Export the v2 app DB (epc_v2.sqlite) from epc_index.sqlite."""
import sqlite3, unicodedata, os

BASE = '/home/hatch/workspace/epc-project'
CATS = ['11SA702', '11SC701']
src = sqlite3.connect(f'{BASE}/epc_index.sqlite')
out_path = f'{BASE}/android/assets/epc_v2.db'
if os.path.exists(out_path): os.remove(out_path)
dst = sqlite3.connect(out_path)

def nfkc(s):
    return unicodedata.normalize('NFKC', s) if s else s

dst.executescript('''
CREATE TABLE catalogs(catalog TEXT PRIMARY KEY, label TEXT);
CREATE TABLE models(catalog TEXT, name TEXT, type_full TEXT, type_code TEXT,
                    grade TEXT, trans TEXT, engine TEXT, serial_from TEXT, serial_to TEXT);
CREATE TABLE groups(catalog TEXT, seq INT, gno TEXT, name TEXT, code TEXT);
CREATE TABLE block_groups(catalog TEXT, block TEXT, group_seq INT, fig_from INT, fig_to INT);
CREATE TABLE blocks(catalog TEXT, block TEXT, figure TEXT, sub TEXT,
                    title TEXT, drawcode TEXT, png TEXT, width INT, height INT);
CREATE TABLE parts(catalog TEXT, block TEXT, figure TEXT, sub TEXT, item TEXT,
                   partno TEXT, name TEXT, name_norm TEXT, price INT, qty INT);
CREATE TABLE hotspots(catalog TEXT, block TEXT, figure TEXT, sub TEXT, item TEXT,
                      x1 INT, y1 INT, x2 INT, y2 INT);
''')

for cat in CATS:
    labels = [' '.join(x) for x in src.execute(
        'SELECT DISTINCT name, type_full FROM models WHERE catalog=? ORDER BY name, type_full', (cat,))]
    dst.execute('INSERT INTO catalogs VALUES (?,?)', (cat, ' / '.join(labels)))
    for r in src.execute('SELECT name, type_full, type_code, grade, trans, engine, serial_from, serial_to '
                         'FROM models WHERE catalog=? ORDER BY name, type_full, grade, trans, serial_from', (cat,)):
        dst.execute('INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?)', (cat,) + r)
    for seq, gno, name, code in src.execute('SELECT seq, gno, name, code FROM groups WHERE catalog=? ORDER BY seq', (cat,)):
        dst.execute('INSERT INTO groups VALUES (?,?,?,?,?)', (cat, seq, gno, nfkc(name), code))
    for block, gseq, ff, ft in src.execute('SELECT block, group_seq, fig_from, fig_to FROM block_groups WHERE catalog=?', (cat,)):
        dst.execute('INSERT INTO block_groups VALUES (?,?,?,?,?)', (cat, block, gseq, ff, ft))
    for block, fig, sub, title, code, png, w, h in src.execute(
            '''SELECT b.block, b.figure, b.sub, b.title, b.drawcode, fm.png, f.width, f.height
               FROM blocks b JOIN figure_map fm
                 ON fm.catalog=b.catalog AND fm.block=b.block AND fm.figure=b.figure AND fm.sub=b.sub
               JOIN figures f ON f.catalog=fm.catalog AND f.png=fm.png
               WHERE b.catalog=?''', (cat,)):
        dst.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?)',
                    (cat, block, fig, sub, nfkc(title), code, png, w, h))
    for block, fig, sub, item, partno, name, price, qty in src.execute(
            'SELECT block, figure, sub, item, partno, name, price, qty FROM parts2 WHERE catalog=?', (cat,)):
        dst.execute('INSERT INTO parts VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (cat, block, fig, sub, item, partno, name, nfkc(name), price, qty))
    for block, fig, sub, item, x1, y1, x2, y2 in src.execute(
            '''SELECT fm.block, fm.figure, fm.sub, hs.item, hs.x1, hs.y1, hs.x2, hs.y2
               FROM figure_map fm
               JOIN figures f ON f.catalog=fm.catalog AND f.png=fm.png
               JOIN hotspots hs ON hs.catalog=f.catalog AND hs.subdir=f.subdir AND hs.filename=f.filename
               WHERE fm.catalog=?''', (cat,)):
        dst.execute('INSERT INTO hotspots VALUES (?,?,?,?,?,?,?,?,?)',
                    (cat, block, fig, sub, item, x1, y1, x2, y2))

dst.executescript('''
CREATE INDEX idx_parts_pn ON parts(partno);
CREATE INDEX idx_parts_nm ON parts(name_norm);
CREATE INDEX idx_parts_fig ON parts(catalog, block, figure, sub);
CREATE INDEX idx_hs_fig ON hotspots(catalog, block, figure, sub);
CREATE INDEX idx_blocks_cat ON blocks(catalog);
CREATE INDEX idx_models_cat ON models(catalog);
''')
dst.commit()
for t in ['catalogs', 'models', 'groups', 'block_groups', 'blocks', 'parts', 'hotspots']:
    print(t, dst.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
dst.close()
print('size:', os.path.getsize(out_path))
print('score dist:', src.execute('SELECT method, COUNT(*), MIN(score), AVG(score) FROM figure_map GROUP BY method').fetchall())
src.close()
