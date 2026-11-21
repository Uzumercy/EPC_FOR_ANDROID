#!/usr/bin/env python3
"""B班 最終検証スクリプト（カタログ内ファイル群）

対象: IBHTBL.CD / PLBTBLJH.CD / KCMST.CD / PLGKTBL.CD / PLCKTBL.CD / MBMJTBL.CD
DISC1 ISO (11CD081) の全82カタログに対して、各ファイルの確定フォーマットで
全件パースし、件数と整合性を検証する。使い方:
    ~/.venvs/gdown/bin/python analysis/verify_b_catalog.py
"""
import struct, re, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from iso_index import load, open_iso, get

files = load()
cats = sorted({p.split('/')[1] for p in files if f"/{p.split('/')[1]}/PLMST.CD" in files})
iso = open_iso()
R = collections.defaultdict(collections.Counter)

def chain(data):
    """u16LE長さチェーン。全件辿ってEOF一致ならレコード列、否ならNone"""
    off = 0; recs = []
    while off < len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < 2 or off + ln > len(data):
            return None
        recs.append(data[off:off+ln]); off += ln
    return recs

for cat in cats:
    # ---- MBMJTBL: [len][code 2B][title 30B cp932][filecode 10B x n] ----
    recs = chain(get(iso, f'/{cat}/MBMJTBL.CD'))
    assert recs is not None, f'MBMJTBL chain fail {cat}'
    R['MBMJTBL']['catalogs'] += 1
    mfiles = {p.split('/')[-1].upper().replace('.', '') for p in files
              if p.startswith(f'/{cat}/M/')}
    codes = []
    for r in recs:
        assert len(r) >= 44 and (len(r) - 34) % 10 == 0
        R['MBMJTBL']['records'] += 1
        n = (len(r) - 34) // 10
        for i in range(n):
            codes.append(r[34+i*10:34+(i+1)*10].decode('ascii').strip())
    R['MBMJTBL']['filecodes'] += len(codes)
    R['MBMJTBL']['filecode_hit'] += sum(1 for c in codes if c in mfiles)
    assert set(codes) == mfiles, f'MBMJTBL filecode set mismatch {cat}'

    # ---- PLCKTBL: 20B固定スロット ----
    raw = get(iso, f'/{cat}/PLCKTBL.CD')
    assert len(raw) % 20 == 0
    R['PLCKTBL']['catalogs'] += 1
    R['PLCKTBL']['slots'] += len(raw) // 20

    # ---- PLGKTBL: 17B固定 [block 1B][from 8B][to 8B] ----
    raw = get(iso, f'/{cat}/PLGKTBL.CD')
    assert len(raw) % 17 == 0
    R['PLGKTBL']['catalogs'] += 1
    for i in range(0, len(raw), 17):
        r = raw[i:i+17]
        assert re.fullmatch(rb'[A-Z]', r[0:1])
        assert re.fullmatch(rb'[A-Z0-9 ]{8}', r[1:9])
        assert re.fullmatch(rb'[A-Z0-9 ]{8}', r[9:17])
        assert r[1:9].strip() or r[9:17].strip()
        R['PLGKTBL']['records'] += 1

    # ---- KCMST: [len][name 50B][value 5B][note 60B x n] ----
    recs = chain(get(iso, f'/{cat}/KCMST.CD'))
    assert recs is not None, f'KCMST chain fail {cat}'
    R['KCMST']['catalogs'] += 1
    for r in recs:
        assert len(r) >= 57 and (len(r) - 57) % 60 == 0
        R['KCMST']['records'] += 1
        R['KCMST']['note_blocks'] += (len(r) - 57) // 60

    # ---- IBHTBL: [len][key 10B][seglen u16 = letters+2][letters] (81カタログ) ----
    if f'/{cat}/IBHTBL.CD' in files:
        recs = chain(get(iso, f'/{cat}/IBHTBL.CD'))
        assert recs is not None, f'IBHTBL chain fail {cat}'
        R['IBHTBL']['catalogs'] += 1
        for r in recs:
            seg = struct.unpack_from('<H', r, 12)[0]
            assert seg == len(r) - 14 + 2
            assert re.fullmatch(rb'[A-Z]*', r[14:])
            R['IBHTBL']['records'] += 1
    else:
        R['IBHTBL']['absent'] += 1

    # ---- PLBTBLJH: 44B固定サイズ表 ----
    raw = get(iso, f'/{cat}/PLBTBLJH.CD')
    assert len(raw) == 44
    g, b = struct.unpack_from('<HH', raw, 0)
    u32s = struct.unpack_from('<9I', raw, 4)
    ibh, mbm = struct.unpack_from('<HH', raw, 40)
    exp = {'GRPTBL.CD': g, 'BLKTBL.CD': b, 'IBHTBL.CD': ibh, 'MBMJTBL.CD': mbm}
    for name, v in zip(['BLKTYTBL.CD', 'PLMSBBI1.CD', 'PLMSBBI2.CD', 'PLMKSBI1.CD',
                        'PLMKSBI2.CD', 'PLMST.CD', 'PLGKTBL.CD', 'PLCKTBL.CD',
                        'KCMST.CD'], u32s):
        exp[name] = v
    for name, v in exp.items():
        actual = files.get(f'/{cat}/{name}')
        assert (actual if actual is not None else 0) == v, \
            f'PLBTBLJH mismatch {cat} {name}: stored {v} actual {actual}'
    R['PLBTBLJH']['catalogs'] += 1

for name in ['MBMJTBL', 'PLCKTBL', 'PLGKTBL', 'KCMST', 'IBHTBL', 'PLBTBLJH']:
    print(name, dict(R[name]))
print('ALL CHECKS PASSED')
iso.close()
