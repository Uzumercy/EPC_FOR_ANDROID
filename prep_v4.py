#!/usr/bin/env python3
"""v4 data prep (all 82 catalogs):
1) Parse GRPTBL/BLKTBL/BLKTYTBL -> groups / block_groups / blocks.
   Title = rec[19:69] fixed 50-byte field (verified strict-cp932 in all
   82 catalogs during recon; fallback = cut at first 4+ space run).
2) Rebuild parts2 from parts (all catalogs).
3) Parse PLMST tails (v3 grammar) -> parts2.codes / gjson / qty, part_groups.
   Positional assignment: parts and parts2 are iterated in the same order.
4) figure_map for all catalogs: drawcode -> filename -> itemset passes.
"""
import json, re, sqlite3, struct, sys

BASE = '/home/hatch/workspace/epc-project'
con = sqlite3.connect(f'{BASE}/epc_index.sqlite')
con.execute('PRAGMA journal_mode=MEMORY')
CATS = [r[0] for r in con.execute('SELECT DISTINCT catalog FROM figures ORDER BY catalog')]
print(f"catalogs: {len(CATS)}", flush=True)

# ---------- 1) tables ----------
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

def parse_title(rec):
    """Fixed 50-byte field at rec[19:69]; fallback: cut at 4+ space run."""
    if len(rec) >= 69:
        try:
            t = rec[19:69].decode('cp932')
            if all(ord(c) >= 0x20 for c in t):
                return re.sub(r' +', ' ', t).strip(), 'fixed50'
        except UnicodeDecodeError:
            pass
    txt = rec[19:].decode('cp932', 'replace')
    txt = re.split(r' {4,}', txt)[0]
    return re.sub(r' +', ' ', txt).strip(), 'fallback'

def parse_blkty(data):
    recs, off = [], 0
    methods = {'fixed50': 0, 'fallback': 0}
    while off + 2 <= len(data):
        ln = struct.unpack('<H', data[off:off+2])[0]
        if ln < 20 or off + ln > len(data): break
        rec = data[off:off+ln]
        fk = rec[2:9]
        title, how = parse_title(rec)
        methods[how] += 1
        recs.append(dict(block=fk[0:3].decode('ascii', 'replace').strip(),
                         fig=fk[3:5].decode('ascii', 'replace').strip(),
                         sub=fk[5:7].decode('ascii', 'replace').strip(),
                         code=rec[9:19].decode('ascii', 'replace').strip(),
                         title=title))
        off += ln
    return recs, methods

con.executescript('''
DROP TABLE IF EXISTS groups; DROP TABLE IF EXISTS block_groups; DROP TABLE IF EXISTS blocks;
CREATE TABLE groups(catalog TEXT, seq INT, gno TEXT, name TEXT, code TEXT);
CREATE TABLE block_groups(catalog TEXT, block TEXT, group_seq INT, fig_from INT, fig_to INT);
CREATE TABLE blocks(catalog TEXT, block TEXT, figure TEXT, sub TEXT, drawcode TEXT, title TEXT);
''')
grp_fail = []
for cat in CATS:
    d = f'{BASE}/cd/extracted/{cat}'
    grps = parse_grp(open(f'{d}/GRPTBL.CD', 'rb').read())
    blks = parse_blk(open(f'{d}/BLKTBL.CD', 'rb').read())
    tys, methods = parse_blkty(open(f'{d}/BLKTYTBL.CD', 'rb').read())
    link2seq = {g['link']: i for i, g in enumerate(grps)}
    for i, g in enumerate(grps):
        con.execute('INSERT INTO groups VALUES (?,?,?,?,?)', (cat, i, g['no'], g['name'], g['code']))
    nbg = 0
    for b in blks:
        seq = link2seq.get(b['link'])
        if seq is None: continue
        con.execute('INSERT INTO block_groups VALUES (?,?,?,?,?)',
                    (cat, b['fblock'], seq, b['fnum'], b['tnum']))
        nbg += 1
    if nbg == 0 and blks:
        grp_fail.append(cat)
    for t in tys:
        con.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?)',
                    (cat, t['block'], t['fig'], t['sub'], t['code'], t['title']))
    print(f"{cat}: groups={len(grps)} blkranges={nbg}/{len(blks)} blocktitles={len(tys)} title_methods={methods}", flush=True)
con.commit()
print("block_groups fallback-needed catalogs:", grp_fail, flush=True)

# fallback: catalogs whose BLKTBL links didn't match get one whole-range entry per block
for cat in grp_fail:
    seqs = [r[0] for r in con.execute('SELECT seq FROM groups WHERE catalog=? ORDER BY seq', (cat,))]
    if not seqs: continue
    blocks_here = [r[0] for r in con.execute('SELECT DISTINCT block FROM blocks WHERE catalog=?', (cat,))]
    for b in blocks_here:
        con.execute('INSERT INTO block_groups VALUES (?,?,?,?,?)', (cat, b, seqs[0], 0, 99999))
    print(f"{cat}: fallback block_groups -> first group, {len(blocks_here)} blocks", flush=True)
con.commit()

# ---------- 2) parts2 ----------
def parse_figkey(fk):
    return (fk[0:3].strip(), fk[3:5].strip(), fk[5:7].strip(), fk[7:10].strip())

con.executescript('''
DROP TABLE IF EXISTS parts2;
CREATE TABLE parts2(catalog TEXT, block TEXT, figure TEXT, sub TEXT, item TEXT,
                    partno TEXT, name TEXT, price INT, qty INT, codes TEXT, gjson TEXT);
''')
rows = con.execute('SELECT catalog, figkey, partno, name, price FROM parts ORDER BY catalog, rowid').fetchall()
con.executemany('INSERT INTO parts2(catalog, block, figure, sub, item, partno, name, price) VALUES (?,?,?,?,?,?,?,?)',
                [(cat, *parse_figkey(fk), partno, name, price) for cat, fk, partno, name, price in rows])
con.commit()
print(f"parts2: {len(rows)} rows", flush=True)
p2_ids = [r[0] for r in con.execute('SELECT rowid FROM parts2 ORDER BY rowid')]
assert len(p2_ids) == len(rows)

# ---------- 3) tails ----------
FIELD = re.compile(rb'^([ ]{0,2}\d{1,3}|[ ]{2}N)$')

def parse_chain(tail, start):
    groups = []
    i = start
    while i < len(tail):
        if i + 9 > len(tail): return None
        glen = struct.unpack('<H', tail[i:i+2])[0]
        if glen < 9 or i + glen > len(tail): return None
        f3 = tail[i+6:i+9]
        if b')' in f3 or f3[:1] == b'(':
            end = tail.find(b')', i+6, i+glen)
            if end < 0: return None
            cs = end + 1
            if (glen - (cs - i)) % 2: return None
            codes = [struct.unpack('<H', tail[j:j+2])[0] for j in range(cs, i+glen-1, 2)]
            groups.append((None, codes))
        elif FIELD.match(f3):
            qty = int(f3.decode('ascii').strip()) if f3.strip().isdigit() else None
            if (glen - 9) % 2: return None
            codes = [struct.unpack('<H', tail[j:j+2])[0] for j in range(i+9, i+glen-1, 2)]
            groups.append((qty, codes))
        else:
            return None
        i += glen
    return groups if i == len(tail) else None

def parse_tail(tail):
    if not tail or len(tail) < 11: return None
    cands = []
    for s in (7 + tail[7], 9, 11, 13, 15):
        if s not in cands: cands.append(s)
    for s in cands:
        g = parse_chain(tail, s)
        if g is not None: return g
    return None

con.executescript('DROP TABLE IF EXISTS part_groups;'
                  'CREATE TABLE part_groups(part_rowid INT, grp_idx INT, qty INT, codes TEXT);')
tail_rows = con.execute('SELECT catalog, partno, tail FROM parts ORDER BY catalog, rowid').fetchall()
assert len(tail_rows) == len(rows)
upd, pg, stats = [], [], {}
for (cat, fk, partno, name, price), (cat2, partno2, tail), rowid in zip(rows, tail_rows, p2_ids):
    assert cat == cat2 and partno == partno2, (cat, partno, partno2)
    groups = parse_tail(tail)
    ok, fail = stats.get(cat, (0, 0))
    if groups is None:
        groups = []
        stats[cat] = (ok, fail + 1)
    else:
        stats[cat] = (ok + 1, fail)
    union = sorted({c for _, cs in groups for c in cs})
    gjson = json.dumps([[q, cs] for q, cs in groups], separators=(',', ':'))
    default_qty = next((q for q, _ in groups if q is not None), None)
    upd.append((','.join(map(str, union)), gjson, default_qty, rowid))
    for gi, (q, cs) in enumerate(groups):
        pg.append((rowid, gi, q, ','.join(map(str, cs))))
con.executemany('UPDATE parts2 SET codes=?, gjson=?, qty=? WHERE rowid=?', upd)
con.executemany('INSERT INTO part_groups VALUES (?,?,?,?)', pg)
con.commit()
tot_ok = sum(v[0] for v in stats.values()); tot_fail = sum(v[1] for v in stats.values())
print(f"tails: ok={tot_ok} fail={tot_fail} ({tot_ok/(tot_ok+tot_fail):.2%})", flush=True)
for cat in CATS:
    ok, fail = stats.get(cat, (0, 0))
    if fail: print(f"   tail-fail {cat}: ok={ok} fail={fail}", flush=True)
print("parts2 with codes:", con.execute("SELECT COUNT(*) FROM parts2 WHERE codes <> ''").fetchone()[0], flush=True)

# ---------- 4) figure_map ----------
con.executescript('''
DROP TABLE IF EXISTS figure_map;
CREATE TABLE figure_map(catalog TEXT, block TEXT, figure TEXT, sub TEXT,
                        png TEXT, method TEXT, score REAL);
''')
total_unassigned = []
for cat in CATS:
    variants = {}
    for block, fig, sub, item in con.execute(
            'SELECT DISTINCT block, figure, sub, item FROM parts2 WHERE catalog=?', (cat,)):
        variants.setdefault((block, fig, sub), set()).add(item)
    for block, fig, sub in con.execute('SELECT block, figure, sub FROM blocks WHERE catalog=?', (cat,)):
        variants.setdefault((block, fig, sub), set())
    files = {}       # filename -> list of entries
    by_png = {}
    for subdir, filename, png in con.execute(
            'SELECT subdir, filename, png FROM figures WHERE catalog=?', (cat,)):
        items = {r[0] for r in con.execute(
            'SELECT DISTINCT item FROM hotspots WHERE catalog=? AND subdir=? AND filename=?',
            (cat, subdir, filename))}
        e = dict(png=png, items=items, used=False)
        files.setdefault(filename, []).append(e)
        by_png[png] = e
    dc = {(b, f, s): c for b, f, s, c in con.execute(
        'SELECT block, figure, sub, drawcode FROM blocks WHERE catalog=?', (cat,))}
    def score(vitems, fitems):
        return (len(vitems & fitems) / len(vitems)) if vitems else 0.0
    stats = {'drawcode': 0, 'filename': 0, 'itemset': 0}
    assigned = {}
    def assign(key, entry, method, sc):
        con.execute('INSERT INTO figure_map VALUES (?,?,?,?,?,?,?)',
                    (cat, key[0], key[1], key[2], entry['png'], method, round(sc, 3)))
        entry['used'] = True
        assigned[key] = entry
    # pass 1: drawcode
    for key, vitems in sorted(variants.items()):
        code = dc.get(key)
        if not code: continue
        cands = [code]
        for k in (1, 2, 3):
            if len(code) > k: cands.append(code[:-k] + '.' + code[-k:])
        entries = [e for c in cands for e in files.get(c, [])]
        if entries:
            cand = max(entries, key=lambda e: score(vitems, e['items']))
            assign(key, cand, 'drawcode', score(vitems, cand['items']))
            stats['drawcode'] += 1
    # pass 2: filename pattern
    pat = re.compile(r'^[A-Z]{2}\d{2}([A-Z])(\d{3})\.(\d)$')
    file_by_bf = {}
    for fn, entries in files.items():
        m = pat.match(fn)
        if m:
            for e in entries:
                file_by_bf.setdefault((m.group(1), str(int(m.group(2)) // 10), m.group(3)), []).append(e)
    for key, vitems in sorted(variants.items()):
        if key in assigned: continue
        for suffix_want in ((key[2],) if key[2] else ('0', '')):
            hit = None
            for e in file_by_bf.get((key[0], key[1], suffix_want), []):
                if not e['used']: hit = e; break
            if hit:
                assign(key, hit, 'filename', score(vitems, hit['items']))
                stats['filename'] += 1
                break
    # pass 3: item-set greedy (pruned: candidate must share >=1 item)
    for key, vitems in sorted(variants.items()):
        if key in assigned or not vitems: continue
        best, bestsc = None, 0.0
        for fn, entries in files.items():
            for e in entries:
                if e['used']: continue
                inter = len(vitems & e['items'])
                if not inter: continue
                sc = inter / len(vitems)
                if sc > bestsc: best, bestsc = e, sc
        if best and bestsc >= 0.7:
            assign(key, best, 'itemset', bestsc)
            stats['itemset'] += 1
    unassigned = [k for k in variants if k not in assigned]
    unused = [e['png'] for e in by_png.values() if not e['used']]
    print(f"{cat}: variants={len(variants)} assigned={stats} unassigned={len(unassigned)} unused_files={len(unused)}", flush=True)
    for k in unassigned: total_unassigned.append((cat,) + k)
con.commit()
print("figure_map total:", con.execute('SELECT COUNT(*) FROM figure_map').fetchone()[0])
print("UNASSIGNED variants:", len(total_unassigned))
for u in total_unassigned[:60]: print("   ", u)
con.close()
print("DONE")
