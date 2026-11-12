"""Conversion stages.

Stage graph (each stage writes a stamp file on success):

    extract    ISO(s) -> work/extracted/*.CD + work/catalogs.json
    index      extracted .CD -> work/index.sqlite
               (models, equip, groups, block_groups, blocks,
                parts, parts2, part_groups)
    figures    ISO(s) -> work/figures/**/*.png + index.sqlite
               (figures, hotspots)
    figuremap  index.sqlite -> figure_map (needs index + figures)
    export     index.sqlite -> out/epc_v4.db        (the app database)
    packs      figures + index.sqlite -> out/packs/<catalog>.zip
    ipad       app DB + figures -> out/epc-<...>.html (opt-in)

The implementations are ports of prep_v4.py / batch_decode.py /
export_v4.py / make_packs.py with paths parameterized.
"""
import io
import json
import os
import re
import sqlite3
import struct
import sys
import unicodedata
import zipfile

from PIL import Image

from . import parsers
from .isosrc import ROOT_FILES

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))

INDEX_SCHEMA = '''
CREATE TABLE IF NOT EXISTS parts(catalog TEXT, figkey TEXT, partno TEXT,
                                 name TEXT, price INTEGER, tail BLOB);
CREATE TABLE IF NOT EXISTS models(idx INTEGER, code1 TEXT, code2 TEXT,
    name TEXT, type_full TEXT, type_code TEXT, serial_from TEXT,
    serial_to TEXT, grade TEXT, trans TEXT, engine TEXT, catalog TEXT,
    tail BLOB, ids TEXT);
CREATE TABLE IF NOT EXISTS equip(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS groups(catalog TEXT, seq INT, gno TEXT,
                                  name TEXT, code TEXT);
CREATE TABLE IF NOT EXISTS block_groups(catalog TEXT, block TEXT,
    group_seq INT, fig_from INT, fig_to INT);
CREATE TABLE IF NOT EXISTS blocks(catalog TEXT, block TEXT, figure TEXT,
    sub TEXT, drawcode TEXT, title TEXT);
CREATE TABLE IF NOT EXISTS parts2(catalog TEXT, block TEXT, figure TEXT,
    sub TEXT, item TEXT, partno TEXT, name TEXT, price INT, qty INT,
    codes TEXT, gjson TEXT);
CREATE TABLE IF NOT EXISTS part_groups(part_rowid INT, grp_idx INT,
                                       qty INT, codes TEXT);
CREATE TABLE IF NOT EXISTS figures(catalog TEXT, subdir TEXT,
    filename TEXT, width INT, height INT, png TEXT, hotspots INT);
CREATE TABLE IF NOT EXISTS hotspots(catalog TEXT, subdir TEXT,
    filename TEXT, item TEXT, x1 INT, y1 INT, x2 INT, y2 INT);
CREATE TABLE IF NOT EXISTS figure_map(catalog TEXT, block TEXT,
    figure TEXT, sub TEXT, png TEXT, method TEXT, score REAL);
'''


class Ctx:
    def __init__(self, args, discs, log):
        self.discs = discs
        self.log = log
        self.out_dir = args.out
        self.work_dir = args.work
        self.extracted_dir = os.path.join(args.work, 'extracted')
        self.figures_dir = os.path.join(args.work, 'figures')
        self.index_db = os.path.join(args.work, 'index.sqlite')
        self.app_db = os.path.join(args.out, 'epc_v4.db')
        self.packs_dir = os.path.join(args.out, 'packs')
        self.ipad_catalogs = args.ipad_catalogs
        self.html_path = args.html or os.path.join(
            PROJECT, 'android', 'assets', 'index.html')

    def catalogs(self):
        with open(os.path.join(self.work_dir, 'catalogs.json')) as f:
            return json.load(f)['catalogs']


def _connect_index(ctx, create=False):
    if create:
        con = sqlite3.connect(ctx.index_db)
        con.executescript(INDEX_SCHEMA)
        return con
    if not os.path.exists(ctx.index_db):
        raise SystemExit(f'index database not found: {ctx.index_db} '
                         '(run the "index" stage first)')
    return sqlite3.connect(ctx.index_db)


# ---------------------------------------------------------------- extract --
def stage_extract(ctx):
    discs = ctx.discs
    cats = discs.catalogs()
    missing = discs.missing_catalog_files()
    if missing:
        detail = '; '.join(f'{c}: {", ".join(m)}'
                            for c, m in sorted(missing.items()))
        raise SystemExit(f'catalog data files missing on the ISO(s): {detail}')
    os.makedirs(ctx.extracted_dir, exist_ok=True)
    root_from = {}
    for name in ROOT_FILES:
        data = discs.root_file(name)
        if data is None:
            raise SystemExit(f'root file {name} not found on any ISO')
        with open(os.path.join(ctx.extracted_dir, name), 'wb') as f:
            f.write(data)
        root_from[name] = discs.root_file_disc(name)
    total = 0
    for i, cat in enumerate(cats, 1):
        d = os.path.join(ctx.extracted_dir, cat)
        os.makedirs(d, exist_ok=True)
        for name in ('PLMST.CD', 'GRPTBL.CD', 'BLKTBL.CD', 'BLKTYTBL.CD'):
            data = discs.catalog_file(cat, name)
            with open(os.path.join(d, name), 'wb') as f:
                f.write(data)
            total += len(data)
        if i % 20 == 0 or i == len(cats):
            ctx.log(f'extract: {i}/{len(cats)} catalogs')
    meta = {'catalogs': cats,
            'catalog_disc': {c: discs.catalog_disc(c) for c in cats},
            'root_files_from_disc': root_from,
            'iso_paths': discs.paths}
    with open(os.path.join(ctx.work_dir, 'catalogs.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    return {'catalogs': len(cats), 'extracted_bytes': total,
            'root_files_from_disc': root_from}


# ------------------------------------------------------------------ index --
def _index_models(ctx, con):
    models = parsers.parse_ksrbhmh(
        os.path.join(ctx.extracted_dir, 'KSRBHMH.CD'))
    con.execute('DELETE FROM models')
    con.executemany(
        'INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        [(m['idx'], m['code1'], m['code2'], m['name'], m['type_full'],
          m['type_code'], m['serial_from'], m['serial_to'], m['grade'],
          m['trans'], m['engine'], m['catalog'], m['tail'], m['ids'])
         for m in models])
    equip = parsers.parse_sysbmst(
        os.path.join(ctx.extracted_dir, 'SYSBMST.CD'))
    con.execute('DELETE FROM equip')
    con.executemany('INSERT INTO equip VALUES (?,?)', equip)
    con.commit()
    fffd = sum(1 for m in models
               if any('�' in (m[c] or '') for c in
                      ('name', 'grade', 'engine', 'type_full')))
    ctx.log(f'index: models={len(models)} equip={len(equip)} '
            f'rows_with_fffd={fffd}')
    return len(models), len(equip)


def _index_tables(ctx, con, cats):
    grp_fail = []
    for cat in cats:
        d = os.path.join(ctx.extracted_dir, cat)
        grps = parsers.parse_grp(open(os.path.join(d, 'GRPTBL.CD'), 'rb').read())
        blks = parsers.parse_blk(open(os.path.join(d, 'BLKTBL.CD'), 'rb').read())
        tys, _methods = parsers.parse_blkty(
            open(os.path.join(d, 'BLKTYTBL.CD'), 'rb').read())
        con.execute('DELETE FROM groups WHERE catalog=?', (cat,))
        con.execute('DELETE FROM block_groups WHERE catalog=?', (cat,))
        con.execute('DELETE FROM blocks WHERE catalog=?', (cat,))
        link2seq = {g['link']: i for i, g in enumerate(grps)}
        for i, g in enumerate(grps):
            con.execute('INSERT INTO groups VALUES (?,?,?,?,?)',
                        (cat, i, g['no'], g['name'], g['code']))
        nbg = 0
        for b in blks:
            seq = link2seq.get(b['link'])
            if seq is None:
                continue
            con.execute('INSERT INTO block_groups VALUES (?,?,?,?,?)',
                        (cat, b['fblock'], seq, b['fnum'], b['tnum']))
            nbg += 1
        if nbg == 0 and blks:
            grp_fail.append(cat)
        for t in tys:
            con.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?)',
                        (cat, t['block'], t['fig'], t['sub'], t['code'],
                         t['title']))
    # fallback (as in prep_v4): catalogs whose BLKTBL links matched no
    # group get one whole-range entry per block under the first group
    for cat in grp_fail:
        seqs = [r[0] for r in con.execute(
            'SELECT seq FROM groups WHERE catalog=? ORDER BY seq', (cat,))]
        if not seqs:
            continue
        blocks_here = [r[0] for r in con.execute(
            'SELECT DISTINCT block FROM blocks WHERE catalog=?', (cat,))]
        for b in blocks_here:
            con.execute('INSERT INTO block_groups VALUES (?,?,?,?,?)',
                        (cat, b, seqs[0], 0, 99999))
        ctx.log(f'index: {cat}: fallback block_groups -> first group, '
                f'{len(blocks_here)} blocks')
    con.commit()
    n = con.execute('SELECT COUNT(*) FROM blocks').fetchone()[0]
    ctx.log(f'index: tables done, blocks={n}')
    return n


def _index_parts(ctx, con, cats):
    con.execute('DELETE FROM parts')
    total = 0
    for i, cat in enumerate(cats, 1):
        data = open(os.path.join(ctx.extracted_dir, cat, 'PLMST.CD'),
                    'rb').read()
        recs = parsers.parse_plmst(data)   # raises unless chain == EOF
        con.executemany(
            'INSERT INTO parts (catalog, figkey, partno, name, price, tail)'
            ' VALUES (?,?,?,?,?,?)',
            [(cat,) + r for r in recs])
        total += len(recs)
        if i % 20 == 0 or i == len(cats):
            ctx.log(f'index: parts {i}/{len(cats)} catalogs, {total} rows')
    con.commit()

    # parts2 + tails (positional, same as prep_v4 steps 2-3)
    con.execute('DELETE FROM parts2')
    con.execute('DELETE FROM part_groups')
    rows = con.execute(
        'SELECT catalog, figkey, partno, name, price FROM parts'
        ' ORDER BY catalog, rowid').fetchall()
    con.executemany(
        'INSERT INTO parts2(catalog, block, figure, sub, item, partno,'
        ' name, price) VALUES (?,?,?,?,?,?,?,?)',
        [(cat, *parsers.parse_figkey(fk), partno, name, price)
         for cat, fk, partno, name, price in rows])
    con.commit()
    p2_ids = [r[0] for r in con.execute('SELECT rowid FROM parts2'
                                        ' ORDER BY rowid')]
    assert len(p2_ids) == len(rows)
    tail_rows = con.execute(
        'SELECT catalog, partno, tail FROM parts ORDER BY catalog, rowid'
    ).fetchall()
    assert len(tail_rows) == len(rows)
    upd, pg = [], []
    ok = fail = 0
    for (cat, fk, partno, name, price), (cat2, partno2, tail), rowid in \
            zip(rows, tail_rows, p2_ids):
        assert cat == cat2 and partno == partno2, (cat, partno, partno2)
        groups = parsers.parse_tail(tail)
        if groups is None:
            groups = []
            fail += 1
        else:
            ok += 1
        union = sorted({c for _, cs in groups for c in cs})
        gjson = json.dumps([[q, cs] for q, cs in groups],
                           separators=(',', ':'))
        default_qty = next((q for q, _ in groups if q is not None), None)
        upd.append((','.join(map(str, union)), gjson, default_qty, rowid))
        for gi, (q, cs) in enumerate(groups):
            pg.append((rowid, gi, q, ','.join(map(str, cs))))
    con.executemany('UPDATE parts2 SET codes=?, gjson=?, qty=?'
                    ' WHERE rowid=?', upd)
    con.executemany('INSERT INTO part_groups VALUES (?,?,?,?)', pg)
    con.commit()
    ctx.log(f'index: parts2={len(rows)} tails ok={ok} fail={fail} '
            f'({ok / (ok + fail):.2%})')
    return {'parts': total, 'tails_ok': ok, 'tails_fail': fail}


def stage_index(ctx):
    if not os.path.exists(os.path.join(ctx.work_dir, 'catalogs.json')):
        raise SystemExit('catalogs.json not found (run "extract" first)')
    cats = ctx.catalogs()
    con = _connect_index(ctx, create=True)
    try:
        n_models, n_equip = _index_models(ctx, con)
        n_blocks = _index_tables(ctx, con, cats)
        part_stats = _index_parts(ctx, con, cats)
    finally:
        con.close()
    return {'models': n_models, 'equip': n_equip, 'blocks': n_blocks,
            **part_stats}


# ---------------------------------------------------------------- figures --
def stage_figures(ctx):
    os.makedirs(ctx.figures_dir, exist_ok=True)
    con = _connect_index(ctx, create=True)
    con.execute('DELETE FROM figures')
    con.execute('DELETE FROM hotspots')
    n_ok = n_fail = n_skip = 0
    fails = []
    try:
        for catalog, subdir, name, data in ctx.discs.walk_figure_files():
            # first segment must be the image segment ('3'), followed by
            # 7 spaces — the identification used by batch_decode.py
            if len(data) < 21 or data[3] != 0x33:
                n_skip += 1
                continue
            if data[4:11] != b'       ':
                n_skip += 1
                continue
            w = struct.unpack('>H', data[11:13])[0]
            h = struct.unpack('>H', data[13:15])[0]
            seg3len = struct.unpack('>H', data[1:3])[0]
            if not (100 <= w <= 4000 and 100 <= h <= 4000
                    and 25 <= seg3len <= len(data)):
                n_skip += 1
                continue
            stream = data[21:seg3len]
            spots = parsers.parse_hotspots(data)
            rel = (f'{catalog}/{subdir}/{name}.png' if subdir
                   else f'{catalog}/{name}.png')
            outpath = os.path.join(ctx.figures_dir, rel)
            os.makedirs(os.path.dirname(outpath), exist_ok=True)
            try:
                im = Image.open(io.BytesIO(parsers.make_tiff(stream, w, h)))
                im.load()
                im.save(outpath, optimize=True)
            except Exception as ex:
                n_fail += 1
                fails.append(f'{rel}: {ex!r}'[:120])
                continue
            con.execute('INSERT INTO figures VALUES (?,?,?,?,?,?,?)',
                        (catalog, subdir, name, w, h, rel, len(spots)))
            for item, x1, y1, x2, y2 in spots:
                con.execute('INSERT INTO hotspots VALUES (?,?,?,?,?,?,?,?)',
                            (catalog, subdir, name, item, x1, y1, x2, y2))
            n_ok += 1
            if n_ok % 1000 == 0:
                con.commit()
                ctx.log(f'figures: decoded {n_ok}')
    finally:
        con.commit()
        con.close()
    ctx.log(f'figures: ok={n_ok} fail={n_fail} skip={n_skip}')
    for f in fails[:20]:
        ctx.log(f'figures: DECODEFAIL {f}')
    if n_fail:
        raise SystemExit(f'figure decode failures: {n_fail} '
                         '(the reference conversion has 0)')
    return {'figures': n_ok, 'decode_fail': n_fail, 'skipped_files': n_skip}


# ------------------------------------------------------------- figuremap --
def stage_figuremap(ctx):
    """Assign each (block, figure, sub) variant its figure PNG.

    Port of prep_v4.py step 4: drawcode match (with '.' inserted before
    the last 1-3 chars), then filename pattern, then best item-set
    overlap >= 0.7.  On DISC1 this assigns 15,291/15,291 variants.
    """
    con = _connect_index(ctx)
    cats = ctx.catalogs()
    con.execute('DELETE FROM figure_map')
    total_unassigned = []
    total_assigned = 0
    try:
        for cat in cats:
            variants = {}
            for block, fig, sub, item in con.execute(
                    'SELECT DISTINCT block, figure, sub, item FROM parts2'
                    ' WHERE catalog=?', (cat,)):
                variants.setdefault((block, fig, sub), set()).add(item)
            for block, fig, sub in con.execute(
                    'SELECT block, figure, sub FROM blocks'
                    ' WHERE catalog=?', (cat,)):
                variants.setdefault((block, fig, sub), set())
            files = {}
            by_png = {}
            for subdir, filename, png in con.execute(
                    'SELECT subdir, filename, png FROM figures'
                    ' WHERE catalog=?', (cat,)):
                items = {r[0] for r in con.execute(
                    'SELECT DISTINCT item FROM hotspots WHERE catalog=?'
                    ' AND subdir=? AND filename=?', (cat, subdir, filename))}
                e = dict(png=png, items=items, used=False)
                files.setdefault(filename, []).append(e)
                by_png[png] = e
            dc = {(b, f, s): c for b, f, s, c in con.execute(
                'SELECT block, figure, sub, drawcode FROM blocks'
                ' WHERE catalog=?', (cat,))}

            def score(vitems, fitems):
                return (len(vitems & fitems) / len(vitems)) if vitems else 0.0

            stats = {'drawcode': 0, 'filename': 0, 'itemset': 0}
            assigned = {}

            def assign(key, entry, method, sc):
                con.execute('INSERT INTO figure_map VALUES (?,?,?,?,?,?,?)',
                            (cat, key[0], key[1], key[2], entry['png'],
                             method, round(sc, 3)))
                entry['used'] = True
                assigned[key] = entry

            # pass 1: drawing code
            for key, vitems in sorted(variants.items()):
                code = dc.get(key)
                if not code:
                    continue
                cands = [code]
                for k in (1, 2, 3):
                    if len(code) > k:
                        cands.append(code[:-k] + '.' + code[-k:])
                entries = [e for c in cands for e in files.get(c, [])]
                if entries:
                    cand = max(entries,
                               key=lambda e: score(vitems, e['items']))
                    assign(key, cand, 'drawcode', score(vitems, cand['items']))
                    stats['drawcode'] += 1
            # pass 2: filename pattern
            pat = re.compile(r'^[A-Z]{2}\d{2}([A-Z])(\d{3})\.(\d)$')
            file_by_bf = {}
            for fn, entries in files.items():
                m = pat.match(fn)
                if m:
                    for e in entries:
                        file_by_bf.setdefault(
                            (m.group(1), str(int(m.group(2)) // 10),
                             m.group(3)), []).append(e)
            for key, vitems in sorted(variants.items()):
                if key in assigned:
                    continue
                for suffix_want in ((key[2],) if key[2] else ('0', '')):
                    hit = None
                    for e in file_by_bf.get((key[0], key[1], suffix_want),
                                            []):
                        if not e['used']:
                            hit = e
                            break
                    if hit:
                        assign(key, hit, 'filename',
                               score(vitems, hit['items']))
                        stats['filename'] += 1
                        break
            # pass 3: item-set greedy
            for key, vitems in sorted(variants.items()):
                if key in assigned or not vitems:
                    continue
                best, bestsc = None, 0.0
                for fn, entries in files.items():
                    for e in entries:
                        if e['used']:
                            continue
                        inter = len(vitems & e['items'])
                        if not inter:
                            continue
                        sc = inter / len(vitems)
                        if sc > bestsc:
                            best, bestsc = e, sc
                if best and bestsc >= 0.7:
                    assign(key, best, 'itemset', bestsc)
                    stats['itemset'] += 1
            unassigned = [k for k in variants if k not in assigned]
            unused = [e['png'] for e in by_png.values() if not e['used']]
            total_assigned += len(assigned)
            ctx.log(f'figuremap: {cat}: variants={len(variants)} '
                    f'assigned={stats} unassigned={len(unassigned)} '
                    f'unused_files={len(unused)}')
            for k in unassigned:
                total_unassigned.append((cat,) + k)
        con.commit()
    finally:
        con.close()
    ctx.log(f'figuremap: total={total_assigned} '
            f'unassigned={len(total_unassigned)}')
    return {'assigned': total_assigned,
            'unassigned': len(total_unassigned),
            'unassigned_keys': [list(u) for u in total_unassigned[:100]]}


# ----------------------------------------------------------------- export --
def _nfkc(s):
    return unicodedata.normalize('NFKC', s) if s else s


def stage_export(ctx):
    """Build the Android app database (port of export_v4.py).

    Schema is normalized around blocks.blkid; part ids are the parts2
    rowids (stable across exports of the same input), and each part's
    applicability code union is rebuilt by the app from gjson, so no
    separate codes column is stored (~40 MB saved).
    """
    src = _connect_index(ctx)
    os.makedirs(ctx.out_dir, exist_ok=True)
    if os.path.exists(ctx.app_db):
        os.remove(ctx.app_db)
    dst = sqlite3.connect(ctx.app_db)
    dst.execute('PRAGMA page_size=4096')
    try:
        dst.executescript('''
CREATE TABLE catalogs(catalog TEXT PRIMARY KEY, label TEXT);
CREATE TABLE models(catalog TEXT, name TEXT, type_full TEXT, type_code TEXT,
                    grade TEXT, trans TEXT, engine TEXT, serial_from TEXT,
                    serial_to TEXT, ids TEXT);
CREATE TABLE groups(catalog TEXT, seq INT, gno TEXT, name TEXT, code TEXT);
CREATE TABLE block_groups(catalog TEXT, block TEXT, group_seq INT,
                          fig_from INT, fig_to INT);
CREATE TABLE blocks(blkid INTEGER PRIMARY KEY, catalog TEXT, block TEXT,
                    figure TEXT, sub TEXT, title TEXT, drawcode TEXT,
                    png TEXT, width INT, height INT);
CREATE TABLE parts(id INTEGER PRIMARY KEY, blkid INT, item TEXT,
                   partno TEXT, name_norm TEXT, price INT, qty INT,
                   gjson TEXT);
CREATE TABLE hotspots(blkid INT, item TEXT, x1 INT, y1 INT, x2 INT, y2 INT);
CREATE TABLE equip(id INTEGER PRIMARY KEY, name TEXT);
''')
        for eid, ename in src.execute('SELECT id, name FROM equip ORDER BY id'):
            dst.execute('INSERT INTO equip VALUES (?,?)', (eid, ename))
        dst.commit()

        cats = [r[0] for r in src.execute(
            'SELECT DISTINCT catalog FROM parts2 ORDER BY catalog')]
        blkid_of = {}
        next_blk = 1
        for cat in cats:
            labels = [' '.join(x) for x in src.execute(
                'SELECT DISTINCT name, type_full FROM models WHERE catalog=?'
                ' ORDER BY name, type_full', (cat,))]
            dst.execute('INSERT INTO catalogs VALUES (?,?)',
                        (cat, ' / '.join(labels)))
            for r in src.execute(
                    'SELECT name, type_full, type_code, grade, trans, engine,'
                    ' serial_from, serial_to, ids FROM models WHERE catalog=?'
                    ' ORDER BY name, type_full, grade, trans, serial_from',
                    (cat,)):
                r = (_nfkc(r[0]), r[1], r[2], _nfkc(r[3])) + r[4:]
                dst.execute('INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?,?)',
                            (cat,) + r)
            for seq, gno, name, code in src.execute(
                    'SELECT seq, gno, name, code FROM groups WHERE catalog=?'
                    ' ORDER BY seq', (cat,)):
                dst.execute('INSERT INTO groups VALUES (?,?,?,?,?)',
                            (cat, seq, gno, _nfkc(name), code))
            for block, gseq, ff, ft in src.execute(
                    'SELECT block, group_seq, fig_from, fig_to'
                    ' FROM block_groups WHERE catalog=?', (cat,)):
                dst.execute('INSERT INTO block_groups VALUES (?,?,?,?,?)',
                            (cat, block, gseq, ff, ft))

            blk_meta = {}
            for block, fig, sub, title, code in src.execute(
                    'SELECT block, figure, sub, title, drawcode FROM blocks'
                    ' WHERE catalog=?', (cat,)):
                blk_meta[(block, fig, sub)] = (title, code)
            variants = {}
            for block, fig, sub, png, w, h in src.execute(
                    '''SELECT fm.block, fm.figure, fm.sub, fm.png,
                              f.width, f.height
                       FROM figure_map fm
                       JOIN figures f ON f.catalog=fm.catalog AND f.png=fm.png
                       WHERE fm.catalog=?''', (cat,)):
                variants[(block, fig, sub)] = (png, w, h)
            for key in blk_meta:
                variants.setdefault(key, (None, None, None))
            for block, fig, sub in src.execute(
                    'SELECT DISTINCT block, figure, sub FROM parts2'
                    ' WHERE catalog=?', (cat,)):
                variants.setdefault((block, fig, sub), (None, None, None))
            for (block, fig, sub), (png, w, h) in sorted(variants.items()):
                title, code = blk_meta.get((block, fig, sub), (None, None))
                dst.execute(
                    'INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (next_blk, cat, block, fig, sub, _nfkc(title), code,
                     png, w, h))
                blkid_of[(cat, block, fig, sub)] = next_blk
                next_blk += 1
        dst.commit()
        ctx.log(f'export: blocks={next_blk - 1}')

        nparts = 0
        for rowid, cat, block, fig, sub, item, partno, name, price, qty, \
                codes, gjson in src.execute(
                    'SELECT rowid, catalog, block, figure, sub, item,'
                    ' partno, name, price, qty, codes, gjson FROM parts2'
                    ' ORDER BY rowid'):
            dst.execute('INSERT INTO parts VALUES (?,?,?,?,?,?,?,?)',
                        (rowid, blkid_of[(cat, block, fig, sub)], item,
                         partno, _nfkc(name), price, qty, gjson))
            nparts += 1
        dst.commit()
        ctx.log(f'export: parts={nparts}')

        nhs = 0
        for cat, block, fig, sub, png in src.execute(
                'SELECT catalog, block, figure, sub, png FROM figure_map'):
            bk = blkid_of.get((cat, block, fig, sub))
            if bk is None:
                continue
            row = src.execute(
                'SELECT subdir, filename FROM figures WHERE catalog=?'
                ' AND png=?', (cat, png)).fetchone()
            subdir, filename = row
            for item, x1, y1, x2, y2 in src.execute(
                    'SELECT item, x1, y1, x2, y2 FROM hotspots'
                    ' WHERE catalog=? AND subdir=? AND filename=?',
                    (cat, subdir, filename)):
                dst.execute('INSERT INTO hotspots VALUES (?,?,?,?,?,?)',
                            (bk, item, x1, y1, x2, y2))
                nhs += 1
        dst.commit()
        ctx.log(f'export: hotspots={nhs}')

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
        counts = {}
        for t in ['catalogs', 'models', 'groups', 'block_groups', 'blocks',
                  'parts', 'hotspots', 'equip']:
            counts[t] = dst.execute(
                f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        counts['blocks_with_png'] = dst.execute(
            'SELECT COUNT(*) FROM blocks WHERE png IS NOT NULL'
        ).fetchone()[0]
    finally:
        dst.close()
        src.close()
    size = os.path.getsize(ctx.app_db)
    ctx.log(f'export: wrote {ctx.app_db} ({size:,} bytes)')
    return {'app_db': ctx.app_db, 'bytes': size, **counts}


# ------------------------------------------------------------------ packs --
def stage_packs(ctx):
    """Per-catalog figure packs (port of make_packs.py): ZIP_STORED,
    entries named exactly as figures.png."""
    con = _connect_index(ctx)
    os.makedirs(ctx.packs_dir, exist_ok=True)
    cats = [r[0] for r in con.execute(
        'SELECT DISTINCT catalog FROM figures ORDER BY catalog')]
    total = 0
    made = 0
    try:
        for cat in cats:
            pngs = [r[0] for r in con.execute(
                'SELECT png FROM figures WHERE catalog=? ORDER BY png',
                (cat,))]
            out = os.path.join(ctx.packs_dir, f'{cat}.zip')
            tmp = out + '.tmp'
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_STORED,
                                 allowZip64=True) as z:
                for png in pngs:
                    z.write(os.path.join(ctx.figures_dir, png), arcname=png)
            os.replace(tmp, out)
            sz = os.path.getsize(out)
            total += sz
            made += 1
            ctx.log(f'packs: {cat}: {len(pngs)} files, {sz / 1e6:.1f} MB')
    finally:
        con.close()
    ctx.log(f'packs: {made} catalogs, {total / 1e6:.1f} MB total')
    return {'packs': made, 'bytes': total}


# ------------------------------------------------------------------- ipad --
def stage_ipad(ctx):
    """Single-file HTML viewer(s) for the given catalogs, generated with
    the project's ipad/build_ipad.py from the freshly built app DB."""
    cats = [c.strip() for c in ctx.ipad_catalogs.split(',') if c.strip()]
    if not cats:
        raise SystemExit('--ipad-catalogs is empty')
    if not os.path.exists(ctx.app_db):
        raise SystemExit(f'app DB not found: {ctx.app_db} '
                         '(run the "export" stage first)')
    if not os.path.exists(ctx.html_path):
        raise SystemExit(f'app HTML not found: {ctx.html_path}')
    build_ipad_path = os.path.join(PROJECT, 'ipad', 'build_ipad.py')
    if not os.path.exists(build_ipad_path):
        raise SystemExit(f'ipad builder not found: {build_ipad_path}')
    import importlib.util
    spec = importlib.util.spec_from_file_location('build_ipad',
                                                  build_ipad_path)
    bi = importlib.util.module_from_spec(spec)
    sys.argv = ['build_ipad.py']   # module only reads argv in main()
    spec.loader.exec_module(bi)
    if cats == ['11SA702', '11SC701']:
        out_name = 'epc-city.html'
    else:
        out_name = 'epc-' + '_'.join(c.lower() for c in cats) + '.html'
    out_path = os.path.join(ctx.out_dir, out_name)
    ctx.log(f'ipad: extracting data for {cats}')
    data = bi.extract(ctx.app_db, ctx.figures_dir, cats)
    bi.build(ctx.html_path, out_path, cats, data)
    size = os.path.getsize(out_path)
    ctx.log(f'ipad: wrote {out_path} ({size:,} bytes); verifying...')
    if not bi.verify(out_path, ctx.app_db, cats):
        raise SystemExit('ipad HTML verification failed')
    return {'html': out_path, 'bytes': size, 'catalogs': cats}
