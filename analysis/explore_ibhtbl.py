#!/usr/bin/env python3
"""B班 探索7: IBHTBL 詳細 + PLGKTBL統一レイアウト再検証 + KCMSTマーカー内訳"""
import struct, re, sys, os, collections, sqlite3
sys.path.insert(0, os.path.dirname(__file__))
from iso_index import load, open_iso, get

files = load()
cats = sorted({p.split('/')[1] for p in files if f"/{p.split('/')[1]}/PLMST.CD" in files})
iso = open_iso()

def chain(data):
    off = 0; recs = []
    while off < len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < 2 or off + ln > len(data):
            return None
        recs.append(data[off:off+ln]); off += ln
    return recs

print('===== IBHTBL: 3カタログ全件 =====')
for cat in ['11SA702', '116790J1', '11S0201']:
    recs = chain(get(iso, f'/{cat}/IBHTBL.CD'))
    print(f'--- {cat}: {len(recs)} records')
    keys = [r[2:12].decode('ascii', errors='replace') for r in recs]
    print('  keys sorted (raw bytes):', keys == sorted(keys))
    for r in recs:
        key = r[2:12].decode('ascii', errors='replace').strip()
        letters = r[14:].decode('ascii', errors='replace')
        print(f'   key={key!r:12s} letters={letters!r}')
    print()

print('===== IBHTBL: 全カタログ集計 =====')
keypat = collections.Counter()
all_letters = collections.Counter()
nrec = 0
for cat in cats:
    if f'/{cat}/IBHTBL.CD' not in files:
        continue
    recs = chain(get(iso, f'/{cat}/IBHTBL.CD'))
    for r in recs:
        nrec += 1
        key = r[2:12].decode('ascii', errors='replace').strip()
        if key == '':
            keypat['(blank)'] += 1
        elif re.fullmatch(r'[A-Z]{1,2}\d+[A-Z]?', key):
            keypat['colorcode-like'] += 1
        else:
            keypat[f'other:{key!r}'] += 1
        all_letters.update(set(r[14:].decode('ascii', errors='replace')))
print('records:', nrec)
print('key patterns:', dict(keypat))
print('letter alphabet (distinct per record, summed):', dict(sorted(all_letters.items())))

print()
print('===== PLGKTBL 統一レイアウト [block 1B][from 8B][to 8B] 全カタログ検証 =====')
tot = collections.Counter()
blockkeys = collections.Counter()
for cat in cats:
    raw = get(iso, f'/{cat}/PLGKTBL.CD')
    for i in range(0, len(raw), 17):
        r = raw[i:i+17]
        blk = chr(r[0])
        frm = r[1:9].decode('ascii', errors='replace')
        to = r[9:17].decode('ascii', errors='replace')
        tot['records'] += 1
        blockkeys[blk] += 1
        if not re.fullmatch(r'[A-Z]', blk):
            tot['bad_block'] += 1
            if tot['bad_block'] <= 5: print('  bad block:', cat, repr(r))
        if frm.strip() and to.strip(): tot['both'] += 1
        elif frm.strip(): tot['from_only'] += 1
        elif to.strip(): tot['to_only'] += 1
        else: tot['both_blank'] += 1
        # フィールド内容の文字種チェック
        if not re.fullmatch(r'[A-Z0-9 ]{8}', frm) or not re.fullmatch(r'[A-Z0-9 ]{8}', to):
            tot['bad_field_chars'] += 1
            if tot['bad_field_chars'] <= 5: print('  bad field:', cat, repr(r))
print(dict(tot))
print('block keys:', dict(sorted(blockkeys.items())))

print()
print('===== PLGKTBL キー vs GRPTBLコード / PLMSTブロック (11SA702) =====')
db = sqlite3.connect(os.path.expanduser('~/workspace/epc-project/epc_index.sqlite'))
print('GRPTBL codes:', db.execute("SELECT DISTINCT code FROM groups WHERE catalog='11SA702'").fetchall())
print('PLMST blocks:', db.execute("SELECT DISTINCT substr(figkey,1,3) FROM parts WHERE catalog='11SA702'").fetchall())

print()
print('===== KCMST マーカー付きエントリの品名 (11SA702) =====')
recs = chain(open(os.path.expanduser('~/workspace/epc-project/cd/extracted/11SA702/KCMST.CD'), 'rb').read())
for r in recs:
    val = r[52:57].decode('ascii', errors='replace').strip()
    if val.startswith('#') or val.startswith('*'):
        print(f'  {val:6s}', r[2:52].decode('cp932', errors='replace').strip())
iso.close()
