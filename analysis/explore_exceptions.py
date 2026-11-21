#!/usr/bin/env python3
"""B班 探索6: 例外ケースの詳細 (MBMJ filecode照合方法, PLCK 11SD201, PLGK 第3形式, KCMST値マーカー, IBHTBL)"""
import struct, re, sys, os, collections
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

print('===== MBMJTBL: filecode を「.除去した実ファイル名」と照合 =====')
tot_code = 0; tot_hit = 0
for cat in cats:
    recs = chain(get(iso, f'/{cat}/MBMJTBL.CD'))
    codes = []
    for r in recs:
        n = (len(r) - 34) // 10
        for i in range(n):
            codes.append(r[34+i*10:34+(i+1)*10].decode('ascii').strip())
    mfiles = {p.split('/')[-1].upper().replace('.', '') for p in files
              if p.startswith(f'/{cat}/M/')}
    tot_code += len(codes)
    tot_hit += sum(1 for c in codes if c in mfiles)
    if set(codes) != mfiles:
        print(f'  {cat}: codes {len(codes)} vs files {len(mfiles)} '
              f'only-code={sorted(set(codes)-mfiles)[:4]} only-file={sorted(mfiles-set(codes))[:4]}')
print(f'filecode total {tot_code}, hit {tot_hit}')

print()
print('===== PLCKTBL 11SD201 の例外スロット周辺 =====')
raw = get(iso, '/11SD201/PLCKTBL.CD')
print('size', len(raw), 'slots', len(raw)//20)
for i in range(len(raw)//20):
    slot = raw[i*20:(i+1)*20]
    txt = slot.decode('cp932', errors='replace')
    if not (txt.strip().startswith('(') and txt.strip().endswith(')')):
        print(' slot', i, repr(txt))
        for j in (i-1, i+1):
            print('   neighbor', j, repr(raw[j*20:(j+1)*20].decode('cp932', errors='replace')))

print()
print('===== PLGKTBL 第3形式 (英数字フレーム) のカタログと構造 =====')
patA = re.compile(rb'^([A-Z0-9]{1,4}) +(\d{7})$')
patB = re.compile(rb'^([A-Z0-9]{1,4}) (\d{7}) (\d{7}| {7})$')
for cat in cats:
    raw = get(iso, f'/{cat}/PLGKTBL.CD')
    unk = []
    for i in range(0, len(raw), 17):
        r = raw[i:i+17]
        if not patA.match(r) and not patB.match(r):
            unk.append(r)
    if unk:
        print(f' {cat}: unknown {len(unk)} / {len(raw)//17}')
        for r in unk[:6]:
            print('   ', repr(r))

print()
print('===== KCMST 値フィールドのマーカー分布 =====')
mark = collections.Counter()
mark_by_cat = collections.defaultdict(collections.Counter)
for cat in cats:
    recs = chain(get(iso, f'/{cat}/KCMST.CD'))
    for r in recs:
        val = r[52:57].decode('ascii', errors='replace').strip()
        if re.fullmatch(r'\d+\.\d+', val):
            k = 'plain'
        elif val == '-':
            k = 'dash'
        elif re.fullmatch(r'#\d+\.\d+', val):
            k = 'hash'
        elif re.fullmatch(r'\*\d+\.\d+', val):
            k = 'star'
        else:
            k = f'other:{val!r}'
        mark[k] += 1
        mark_by_cat[cat][k] += 1
print('total:', dict(mark))
for cat, c in mark_by_cat.items():
    keys = set(c) - {'plain'}
    if keys:
        print(f'  {cat}: {dict(c)}')

print()
print('===== IBHTBL 詳細 (3カタログ全件) =====')
for cat in ['11SA702', '116790J1', '11S0201']:
    if f'/{cat}/IBHTBL.CD' not in files:
        print(cat, 'absent'); continue
    recs = chain(get(iso, f'/{cat}/IBHTBL.CD'))
    print(f'--- {cat}: {len(recs)} records')
    keys = [r[2:12].decode('ascii', errors='replace') for r in recs]
    print('  keys sorted:', keys == sorted(keys), ' distinct keys:', len(set(k.strip() for k in keys)))
    for r in recs[:14]:
        key = r[2:12].decode('ascii', errors='replace').strip()
        letters = r[14:].decode('ascii', errors='replace')
        print(f'   key={key!r:14s} seg={struct.unpack_from("<H", r, 12)[0]:3d} letters={letters!r}')
    allletters = collections.Counter()
    for r in recs:
        allletters.update(r[14:].decode('ascii', errors='replace'))
    print('  letter freq:', dict(sorted(allletters.items())))
iso.close()
