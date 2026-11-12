#!/usr/bin/env python3
"""Rebuild the models table in epc_index.sqlite from KSRBHMH.CD.

v4.5 fix: the original parse decoded text fields with Python's 'shift_jis'
codec, which maps halfwidth katakana bytes (0xA1-0xDF) to U+FFFD
(85 grade rows were garbled, e.g. 'F ' for 'F '). The raw
data is fine; re-parse everything with cp932.

The script first parses + diffs against the existing table and only swaps
the table in when every difference is confined to the known U+FFFD rows
(tail BLOBs and ids strings must match exactly for all rows).

Also builds the equip table from SYSBMST.CD. Key = the record's file
index (0-based; record 0 is a blank dummy). This is the key the model
record tails reference from their 3rd value onward (the first two tail
values are the model's applicability band pair (2k-1, 2k), verified for
all 26,651 records). NOT the u16 stored inside each SYSBMST record:
e.g. tail value 20 -> SYSBMST record #20 '' (u16=89),
26 -> '' (u16=130),
42 -> '' (u16=49) — all three match the
original EPC UI's equipment columns for CITY AA (select4-2).
"""
import re, sqlite3, struct, sys, unicodedata

BASE = '/home/hatch/workspace/epc-project'
FFFD = '�'

def parse_ksrbhmh(path):
    d = open(path, 'rb').read()
    recs, off = [], 0
    while off + 2 <= len(d):
        ln = struct.unpack('<H', d[off:off+2])[0]
        if ln < 105 or off + ln > len(d):
            raise ValueError(f'bad record length {ln} at {off}')
        recs.append(d[off:off+ln])
        off += ln
    if off != len(d):
        raise ValueError(f'chain consumed {off} of {len(d)}')
    out = []
    for i, rec in enumerate(recs):
        def txt(a, b):
            return rec[a:b].decode('cp932').strip()
        # name/type_full boundary: base layout is name [13:29] (16B) +
        # type_full [29:37] (8B), but when type_full then starts with '-'
        # the boundary sits one byte earlier (name [13:28], type_full
        # [28:37]) — e.g. TODAY 'M-JW1' vs INSIGHT 'AA-ZE1'. This is the
        # rule the original parse applied (9,845 shifted records).
        name, type_full = txt(13, 29), txt(29, 37)
        if type_full.startswith('-'):
            name, type_full = txt(13, 28), txt(28, 37)
        tail = rec[105:]
        if len(tail) % 2:
            raise ValueError(f'odd tail at record {i}')
        ids = [struct.unpack_from('<H', tail, j)[0] for j in range(0, len(tail), 2)]
        out.append(dict(
            idx=i, code1=txt(2, 6), code2=txt(6, 13), name=name,
            type_full=type_full, type_code=txt(37, 45),
            serial_from=txt(53, 60), serial_to=txt(61, 68), grade=txt(68, 86),
            trans=txt(86, 89), engine=txt(89, 97), catalog=txt(97, 105),
            tail=tail, ids=','.join(str(v) for v in ids)))
    return out

def parse_sysbmst(path):
    d = open(path, 'rb').read()
    if len(d) % 20:
        raise ValueError(f'SYSBMST size {len(d)} not a multiple of 20')
    rows = []
    for i in range(len(d) // 20):
        name = unicodedata.normalize('NFKC', d[i*20:i*20+18].decode('cp932'))
        name = re.sub(r'\s+', ' ', name).strip()
        rows.append((i, name))
    return rows

def main():
    new = parse_ksrbhmh(f'{BASE}/cd/extracted/KSRBHMH.CD')
    print('parsed records:', len(new))
    con = sqlite3.connect(f'{BASE}/epc_index.sqlite')
    old = con.execute('SELECT idx, code1, code2, name, type_full, type_code,'
                      ' serial_from, serial_to, grade, trans, engine, catalog,'
                      ' tail, ids FROM models ORDER BY idx').fetchall()
    print('existing rows:', len(old))
    if len(new) != len(old):
        sys.exit('ROW COUNT MISMATCH')

    cols = ['code1', 'code2', 'name', 'type_full', 'type_code', 'serial_from',
            'serial_to', 'grade', 'trans', 'engine', 'catalog']
    diffs = {c: 0 for c in cols}
    diff_rows = set()
    tail_bad = ids_bad = 0
    for o, n in zip(old, new):
        assert o[0] == n['idx']
        for k, c in enumerate(cols, start=1):
            if o[k] != n[c]:
                diffs[c] += 1
                diff_rows.add(o[0])
        if o[12] != n['tail']:
            tail_bad += 1
        if o[13] != n['ids']:
            ids_bad += 1
    print('field diffs vs existing:', diffs)
    print('rows with any text diff:', len(diff_rows))
    print('tail mismatches:', tail_bad, '| ids mismatches:', ids_bad)

    fffd_rows = {r[0] for r in old if any(FFFD in (r[k] or '') for k in range(1, 12))}
    print('existing rows containing U+FFFD:', len(fffd_rows))
    if diff_rows != fffd_rows:
        only_new = sorted(diff_rows - fffd_rows)[:10]
        only_old = sorted(fffd_rows - diff_rows)[:10]
        print('UNEXPECTED diff rows (not FFFD rows):', only_new)
        print('FFFD rows without diff:', only_old)
        sys.exit('diff set != FFFD set; NOT swapping')
    if tail_bad:
        sys.exit('tail mismatch; NOT swapping')
    # ids: the stored column was written by a key-matched UPDATE in v3 that
    # over-matched near-duplicate models (890 rows carry a sibling row's
    # ids). The fresh parse derives ids from each record's own tail bytes
    # (identical to the stored tail BLOB for every row), which is the
    # positional re-derivation the task calls for. Verify that claim here.
    if ids_bad:
        bad_explained = 0
        for o, n in zip(old, new):
            if o[13] != n['ids']:
                derived = ','.join(str(struct.unpack_from('<H', o[12], j)[0])
                                   for j in range(0, len(o[12]), 2))
                if derived == n['ids']:
                    bad_explained += 1
        print(f'ids corrections: {ids_bad} rows, all tail-derived: {bad_explained == ids_bad}')
        if bad_explained != ids_bad:
            sys.exit('ids mismatch not explained by tail derivation; NOT swapping')

    new_fffd = sum(1 for n in new if any(FFFD in n[c] for c in cols))
    print('new rows containing U+FFFD:', new_fffd)
    if new_fffd:
        sys.exit('new parse still contains U+FFFD; NOT swapping')

    equip = parse_sysbmst(f'{BASE}/cd/extracted/SYSBMST.CD')
    print('equip records:', len(equip), '| named:', sum(1 for _, nm in equip if nm))
    if len(equip) != 173:
        sys.exit('equip record count != 173')

    cur = con.cursor()
    cur.execute('BEGIN')
    cur.execute('''CREATE TABLE models_new(idx INTEGER, code1 TEXT, code2 TEXT,
        name TEXT, type_full TEXT, type_code TEXT, serial_from TEXT,
        serial_to TEXT, grade TEXT, trans TEXT, engine TEXT, catalog TEXT,
        tail BLOB, ids TEXT)''')
    cur.executemany('INSERT INTO models_new VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    [(n['idx'], n['code1'], n['code2'], n['name'], n['type_full'],
                      n['type_code'], n['serial_from'], n['serial_to'], n['grade'],
                      n['trans'], n['engine'], n['catalog'], n['tail'], n['ids'])
                     for n in new])
    cur.execute('DROP TABLE models')
    cur.execute('ALTER TABLE models_new RENAME TO models')
    cur.execute('DROP TABLE IF EXISTS equip')
    cur.execute('CREATE TABLE equip(id INTEGER PRIMARY KEY, name TEXT)')
    cur.executemany('INSERT INTO equip VALUES (?,?)', equip)
    con.commit()
    print('models swapped; equip created')
    print('models rows now:', con.execute('SELECT COUNT(*) FROM models').fetchone()[0])
    print('FFFD in models now:',
          con.execute("SELECT COUNT(*) FROM models WHERE grade LIKE '%�%' OR"
                      " name LIKE '%�%' OR engine LIKE '%�%'").fetchone()[0])
    con.close()
    print('DONE')

if __name__ == '__main__':
    main()
