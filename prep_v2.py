#!/usr/bin/env python3
"""v2 data prep: parse GRPTBL/BLKTBL/BLKTYTBL, build figure_map, export app DB."""
import re, sqlite3, struct, unicodedata, os, sys

BASE = '/home/hatch/workspace/epc-project'
CATS = ['11SA702', '11SC701']
con = sqlite3.connect(f'{BASE}/epc_index.sqlite')

def nfkc(s):
    return unicodedata.normalize('NFKC', s)

# ---------- Step 1: parse tables ----------
def parse_grp(data):
    recs, off = [], 0
    while off + 2 <= len(data):
        ln = struct.unpack('<H', data[off:off+2])[0]
        if ln < 54 or off + ln > len(data): break
        rec = data[off:off+ln]
        recs.append(dict(no=rec[2:4].decode('ascii', 'replace').strip(),
                         name=rec[4:43].decode('cp932', 'replace').strip(),
                         code=rec[43:46].decode('ascii', 'replace').strip(),
                         link=rec[46:54]))
        off += ln
    return recs

def parse_blk(data):
    recs = []
    for i in range(0, len(data) - 24, 25):
        rec = data[i:i+25]
        span = rec[0:14].decode('ascii', 'replace')
        toks = re.findall(r'([A-Z]+)\s*(\d+)', span)
        if len(toks) < 2: continue
        recs.append(dict(fblock=toks[0][0], fnum=int(toks[0][1]),
                         tblock=toks[1][0], tnum=int(toks[1][1]),
                         link=rec[17:25]))
    return recs

def parse_blkty(data):
    recs, off = [], 0
    while off + 2 <= len(data):
        ln = struct.unpack('<H', data[off:off+2])[0]
        if ln < 20 or off + ln > len(data): break
        rec = data[off:off+ln]
        fk = rec[2:9]  # 7 bytes, same layout as PLMST figkey head
        block = fk[0:3].decode('ascii', 'replace').strip()
        fig = fk[3:5].decode('ascii', 'replace').strip()
        sub = fk[5:7].decode('ascii', 'replace').strip()
        code = rec[9:19].decode('ascii', 'replace').strip()
        raw = rec[19:]
        # title: cp932 text until NUL or undecodable; the text field is
        # space-padded and may hold 2 segments; binary tail can decode to
        # short ASCII junk, so split on 4+ spaces and keep real segments.
        txt = raw.decode('cp932', 'replace')
        cut = len(txt)
        for j, ch in enumerate(txt):
            if ch == '\x00' or ch == '\ufffd':
                cut = j; break
        segs = []
        for seg in re.split(r' {4,}', txt[:cut]):
            seg = re.sub(r'\s+', ' ', seg).strip()
            if len(seg) >= 3 and (re.search(r'[぀-ヿ一-鿿｡-ﾟ]', seg) or
                                  (re.search(r'[A-Za-z]', seg) and re.search(r'\d', seg))):
                segs.append(seg)
        title = ' '.join(segs)
        recs.append(dict(block=block, fig=fig, sub=sub, code=code, title=title))
        off += ln
    return recs

con.executescript('''
DROP TABLE IF EXISTS groups; DROP TABLE IF EXISTS block_groups; DROP TABLE IF EXISTS blocks;
CREATE TABLE groups(catalog TEXT, seq INT, gno TEXT, name TEXT, code TEXT);
CREATE TABLE block_groups(catalog TEXT, block TEXT, group_seq INT, fig_from INT, fig_to INT);
CREATE TABLE blocks(catalog TEXT, block TEXT, figure TEXT, sub TEXT, drawcode TEXT, title TEXT);
''')

for cat in CATS:
    d = f'{BASE}/cd/extracted/{cat}'
    grps = parse_grp(open(f'{d}/GRPTBL.CD', 'rb').read())
    blks = parse_blk(open(f'{d}/BLKTBL.CD', 'rb').read())
    tys = parse_blkty(open(f'{d}/BLKTYTBL.CD', 'rb').read())
    link2seq = {g['link']: i for i, g in enumerate(grps)}
    for i, g in enumerate(grps):
        con.execute('INSERT INTO groups VALUES (?,?,?,?,?)', (cat, i, g['no'], g['name'], g['code']))
    for b in blks:
        seq = link2seq.get(b['link'])
        if seq is None: continue
        con.execute('INSERT INTO block_groups VALUES (?,?,?,?,?)',
                    (cat, b['fblock'], seq, b['fnum'], b['tnum']))
    for t in tys:
        con.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?)',
                    (cat, t['block'], t['fig'], t['sub'], t['code'], t['title']))
    print(f"{cat}: groups={len(grps)} blkranges={len(blks)} blocktitles={len(tys)}")
con.commit()

# ---------- Step 2: figure_map ----------
def parse_figkey(fk):
    return (fk[0:3].strip(), fk[3:5].strip(), fk[5:7].strip(), fk[7:10].strip())

def parse_qty(tail):
    """return (first parseable group qty or None, n_groups, qtys).
    Group = one or more 0xFFFF markers + 3-byte ASCII qty + u16LE code list."""
    if not tail: return None, 0, []
    qtys = []
    i = 11
    while i + 5 <= len(tail):
        if tail[i:i+2] == b'\xff\xff':
            while i + 2 <= len(tail) and tail[i:i+2] == b'\xff\xff':
                i += 2
            if i + 3 > len(tail): break
            q = tail[i:i+3].decode('ascii', 'replace').strip()
            qtys.append(int(q) if q.isdigit() else None)
            i += 3
            while i + 2 <= len(tail) and tail[i:i+2] != b'\xff\xff':
                i += 2
        else:
            i += 1
    first = next((q for q in qtys if q is not None), None)
    return first, len(qtys), qtys

# variant item sets + qty per part (store qty back into a temp table)
con.executescript('''
DROP TABLE IF EXISTS parts2;
CREATE TABLE parts2(catalog TEXT, block TEXT, figure TEXT, sub TEXT, item TEXT,
                    partno TEXT, name TEXT, price INT, qty INT);
DROP TABLE IF EXISTS figure_map;
CREATE TABLE figure_map(catalog TEXT, block TEXT, figure TEXT, sub TEXT,
                        png TEXT, method TEXT, score REAL);
''')
multi_qty = 0; total_parts = 0
for cat in CATS:
    for fk, partno, name, price, tail in con.execute(
            'SELECT figkey, partno, name, price, tail FROM parts WHERE catalog=?', (cat,)):
        block, fig, sub, item = parse_figkey(fk)
        qty, ng, qs = parse_qty(tail)
        total_parts += 1
        if len(set(q for q in qs if q is not None)) > 1: multi_qty += 1
        con.execute('INSERT INTO parts2 VALUES (?,?,?,?,?,?,?,?,?)',
                    (cat, block, fig, sub, item, partno, name, price, qty))
con.commit()
print(f"parts2: {total_parts} rows; parts with differing qtys across groups: {multi_qty}")

for cat in CATS:
    # variant item sets
    variants = {}
    for block, fig, sub, item in con.execute(
            'SELECT DISTINCT block, figure, sub, item FROM parts2 WHERE catalog=?', (cat,)):
        variants.setdefault((block, fig, sub), set()).add(item)
    # files and their hotspot item sets
    files = {}
    for subdir, filename, png in con.execute(
            'SELECT subdir, filename, png FROM figures WHERE catalog=?', (cat,)):
        items = {r[0] for r in con.execute(
            'SELECT DISTINCT item FROM hotspots WHERE catalog=? AND subdir=? AND filename=?',
            (cat, subdir, filename))}
        files[filename] = dict(png=png, items=items, used=False)
    # drawcode lookup from blocks
    dc = {(b, f, s): c for b, f, s, c in con.execute(
        'SELECT block, figure, sub, drawcode FROM blocks WHERE catalog=?', (cat,))}
    stats = {'drawcode': 0, 'filename': 0, 'itemset': 0}
    unassigned = []
    def score(vitems, fitems):
        if not vitems: return 0.0
        return len(vitems & fitems) / len(vitems)
    # pass 1: drawcode
    for key, vitems in sorted(variants.items()):
        code = dc.get(key)
        if not code: continue
        cands = [code]
        for k in (1, 2, 3):
            if len(code) > k: cands.append(code[:-k] + '.' + code[-k:])
        existing = [c for c in cands if c in files]
        if existing:
            cand = max(existing, key=lambda c: score(vitems, files[c]['items']))
            sc = score(vitems, files[cand]['items'])
            con.execute('INSERT INTO figure_map VALUES (?,?,?,?,?,?,?)',
                        (cat, key[0], key[1], key[2], files[cand]['png'], 'drawcode', round(sc, 3)))
            files[cand]['used'] = True
            stats['drawcode'] += 1
    assigned = {(b, f, s) for b, f, s in con.execute(
        'SELECT block, figure, sub FROM figure_map WHERE catalog=?', (cat,))}
    # pass 2: filename pattern SA71E010.2 / SC71E050.0
    pat = re.compile(r'^[A-Z]{2}\d{2}([A-Z])(\d{3})\.(\d)$')
    file_by_bf = {}
    for fn, info in files.items():
        m = pat.match(fn)
        if m: file_by_bf.setdefault((m.group(1), str(int(m.group(2)) // 10)), []).append((fn, m.group(3)))
    for key, vitems in sorted(variants.items()):
        if key in assigned: continue
        for fn, suffix in file_by_bf.get((key[0], key[1]), []):
            if files[fn]['used']: continue
            if suffix == key[2] or (key[2] == '' and suffix == '0'):
                sc = score(vitems, files[fn]['items'])
                con.execute('INSERT INTO figure_map VALUES (?,?,?,?,?,?,?)',
                            (cat, key[0], key[1], key[2], files[fn]['png'], 'filename', round(sc, 3)))
                files[fn]['used'] = True; assigned.add(key); stats['filename'] += 1
                break
    # pass 3: item-set greedy (score >= 0.7, both-direction containment considered via recall)
    for key, vitems in sorted(variants.items()):
        if key in assigned: continue
        best, bestsc = None, 0.0
        for fn, info in files.items():
            if info['used']: continue
            sc = score(vitems, info['items'])
            if sc > bestsc: best, bestsc = fn, sc
        if best and bestsc >= 0.7:
            con.execute('INSERT INTO figure_map VALUES (?,?,?,?,?,?,?)',
                        (cat, key[0], key[1], key[2], files[best]['png'], 'itemset', round(bestsc, 3)))
            files[best]['used'] = True; assigned.add(key); stats['itemset'] += 1
        else:
            unassigned.append((key, round(bestsc, 2)))
    low = con.execute('SELECT block, figure, sub, method, score FROM figure_map WHERE catalog=? AND score < 0.8', (cat,)).fetchall()
    print(f"{cat}: variants={len(variants)} assigned={stats} unassigned={len(unassigned)}")
    for u in unassigned: print("   UNASSIGNED:", u)
    for l in low: print("   LOWSCORE:", l)
    unused = [fn for fn, i in files.items() if not i['used']]
    print(f"   unused files: {len(unused)} {unused[:10]}")
con.commit()
print("figure_map total:", con.execute('SELECT COUNT(*) FROM figure_map').fetchone()[0])
con.close()
print("DONE")
