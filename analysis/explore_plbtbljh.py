#!/usr/bin/env python3
"""B班 探索5: PLBTBLJH のサイズ表仮説を複数カタログで検証"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from iso_index import load, open_iso, get

files = load()
cats = sorted({p.split('/')[1] for p in files
               if p.count('/') >= 2 and not p.startswith('/PROGRAM') and p.split('/')[1] != ''})
# ルートファイルを除く (カタログ = .CD を直接含むディレクトリ)
cats = [c for c in cats if f'/{c}/PLMST.CD' in files]
print('catalogs with PLMST:', len(cats))

iso = open_iso()
ORDER_U32 = ['BLKTYTBL.CD', 'PLMSBBI1.CD', 'PLMSBBI2.CD', 'PLMKSBI1.CD', 'PLMKSBI2.CD',
             'PLMST.CD', 'PLGKTBL.CD', 'PLCKTBL.CD', 'KCMST.CD']

def check(cat):
    raw = get(iso, f'/{cat}/PLBTBLJH.CD')
    if raw is None:
        return (cat, 'NO PLBTBLJH', None)
    if len(raw) != 44:
        return (cat, f'LEN {len(raw)} != 44', None)
    # H2: [u16 GRPTBL][u16 BLKTBL][9 x u32][u16 IBHTBL][u16 MBMJTBL]
    g, b = struct.unpack_from('<HH', raw, 0)
    u32s = struct.unpack_from('<9I', raw, 4)
    ibh, mbm = struct.unpack_from('<HH', raw, 40)
    exp = {'GRPTBL.CD': g, 'BLKTBL.CD': b, 'IBHTBL.CD': ibh, 'MBMJTBL.CD': mbm}
    for name, v in zip(ORDER_U32, u32s):
        exp[name] = v
    mism = []
    for name, v in exp.items():
        actual = files.get(f'/{cat}/{name}')
        if actual != v:
            mism.append((name, v, actual))
    return (cat, 'OK' if not mism else f'MISMATCH {mism}', (g, b, u32s, ibh, mbm))

for cat in ['11SA702', '11S0201', '116790J1', '11SC701', '12SJ601', '11SZ501']:
    if f'/{cat}/PLMST.CD' in files:
        print(check(cat))

# 全カタログで PLBTBLJH の長さ分布と H2 照合
ok = 0; bad = []
lens = {}
for cat in cats:
    raw = get(iso, f'/{cat}/PLBTBLJH.CD')
    lens[len(raw)] = lens.get(len(raw), 0) + 1
    r = check(cat)
    if r[1] == 'OK':
        ok += 1
    else:
        bad.append(r[:2])
print()
print('PLBTBLJH lengths across catalogs:', lens)
print(f'H2 size-table match: {ok}/{len(cats)} catalogs')
for b in bad[:10]:
    print('  BAD:', b)
iso.close()
