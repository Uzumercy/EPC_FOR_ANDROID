#!/usr/bin/env python3
"""v3 data prep:
1) Re-parse BLKTYTBL titles: the title field is a fixed 50-byte field at
   rec[19:69] (verified: all 374 records decode as strict cp932 with no
   control chars; binary tail starts at rec[69]). v2's split-on-4-spaces
   heuristic let the binary tail's first 2 bytes (cp932 halfwidth kana)
   leak into titles. Fixed field + space-collapse removes it and also
   preserves legitimate two-segment titles.
2) Parse PLMST tails with the confirmed grammar and store per-part
   applicability groups (qty, model-ID codes) + union codes.
   Tail = fixed header (groups start at 7 + tail[7]) + chained groups:
     A: [len u16LE][u16][u16][qty ASCII 3B: spaces+digits, or '  N'][codes]
     B: [len u16LE][u16][u16][note ASCII containing ')'][codes]
"""
import json, re, sqlite3, struct

BASE = '/home/hatch/workspace/epc-project'
CATS = ['11SA702', '11SC701']
con = sqlite3.connect(f'{BASE}/epc_index.sqlite')

# ---------- 1) titles ----------
def parse_blkty_titles(data):
    recs, off = [], 0
    while off + 2 <= len(data):
        ln = struct.unpack('<H', data[off:off+2])[0]
        if ln < 20 or off + ln > len(data): break
        rec = data[off:off+ln]
        fk = rec[2:9]
        block = fk[0:3].decode('ascii', 'replace').strip()
        fig = fk[3:5].decode('ascii', 'replace').strip()
        sub = fk[5:7].decode('ascii', 'replace').strip()
        txt = rec[19:69].decode('cp932', 'replace')
        title = re.sub(r' +', ' ', txt).strip()
        recs.append((block, fig, sub, title))
        off += ln
    return recs

n_upd = 0
suspicious = []
for cat in CATS:
    for block, fig, sub, title in parse_blkty_titles(open(f'{BASE}/cd/extracted/{cat}/BLKTYTBL.CD', 'rb').read()):
        cur = con.execute('UPDATE blocks SET title=? WHERE catalog=? AND block=? AND figure=? AND sub=?',
                          (title, cat, block, fig, sub))
        n_upd += cur.rowcount
        # mechanical check: trailing token of 1-2 halfwidth kana chars after a space
        toks = title.split(' ')
        if len(toks) >= 2 and 1 <= len(toks[-1]) <= 2 and all('\uff66' <= c <= '\uff9f' for c in toks[-1]):
            suspicious.append((cat, block, fig, sub, title))
con.commit()
print(f"titles updated: {n_upd}")
print(f"suspicious trailing-kana titles: {len(suspicious)}")
for s in suspicious: print("   SUSPECT:", s)
for cat, b, f, s in [('11SC701', 'B', '19', ''), ('11SC701', 'B', '22', ''),
                     ('11SC701', 'B', '23', ''), ('11SC701', 'B', '24', ''),
                     ('11SA702', 'E', '1', ''), ('11SA702', 'E', '1', '2')]:
    row = con.execute('SELECT title FROM blocks WHERE catalog=? AND block=? AND figure=? AND sub=?',
                      (cat, b, f, s)).fetchone()
    print(f"CHECK {cat} {b}-{f} sub={s!r}: {row[0] if row else None!r}")

# ---------- 2) tail groups ----------
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

def parse_figkey(fk):
    return (fk[0:3].strip(), fk[3:5].strip(), fk[5:7].strip(), fk[7:10].strip())

# parts2 rowid lookup by 6-tuple
p2 = {}
for rowid, cat, block, fig, sub, item, partno in con.execute(
        'SELECT rowid, catalog, block, figure, sub, item, partno FROM parts2'):
    p2.setdefault((cat, block, fig, sub, item, partno), []).append(rowid)

for col in ('codes', 'gjson'):
    try: con.execute(f'ALTER TABLE parts2 ADD COLUMN {col} TEXT')
    except sqlite3.OperationalError: pass
con.executescript('DROP TABLE IF EXISTS part_groups;'
                  'CREATE TABLE part_groups(part_rowid INT, grp_idx INT, qty INT, codes TEXT);')

stats = {}
for cat in CATS:
    ok = fail = multi = 0
    for fk, partno, tail in con.execute('SELECT figkey, partno, tail FROM parts WHERE catalog=?', (cat,)):
        block, fig, sub, item = parse_figkey(fk)
        groups = parse_tail(tail)
        key = (cat, block, fig, sub, item, partno)
        rowids = p2.get(key, [])
        if len(rowids) > 1: multi += 1
        if groups is None:
            fail += 1
            groups = []
        else:
            ok += 1
        union = sorted({c for _, cs in groups for c in cs})
        gjson = json.dumps([[q, cs] for q, cs in groups], separators=(',', ':'))
        default_qty = next((q for q, _ in groups if q is not None), None)
        for rowid in rowids:
            con.execute('UPDATE parts2 SET codes=?, gjson=?, qty=? WHERE rowid=?',
                        (','.join(map(str, union)), gjson, default_qty, rowid))
            for gi, (q, cs) in enumerate(groups):
                con.execute('INSERT INTO part_groups VALUES (?,?,?,?)',
                            (rowid, gi, q, ','.join(map(str, cs))))
    stats[cat] = (ok, fail, multi)
    print(f"{cat}: tail parse ok={ok} fail={fail} multi-rowid keys={multi}")
con.commit()
print("parts2 with codes:", con.execute("SELECT COUNT(*) FROM parts2 WHERE codes IS NOT NULL").fetchone()[0])
print("part_groups rows:", con.execute('SELECT COUNT(*) FROM part_groups').fetchone()[0])
con.close()
print("DONE")
