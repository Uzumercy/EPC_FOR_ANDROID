#!/usr/bin/env python3
"""B班 検証: 対象6ファイルの構造を全82カタログで検証する
- MBMJTBL.CD : 可変長レコード [len u16LE][page code 2B][title 30B cp932][file codes 10B x n]
- PLCKTBL.CD : 20B固定スロット x n （括弧書き用語）
- PLGKTBL.CD : 17B固定レコード x n （A型: block+serial / B型: block+from+to）
- KCMST.CD   : 可変長レコード [len][name 50B][value 5B][note blocks 60B x n]
- IBHTBL.CD  : 可変長レコード [len][10B field][u16 = letters+2][letters]
- PLBTBLJH.CD: 44B固定 サイズ表（別スクリプトで検証済み、ここでは長さのみ）
"""
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

stats = collections.defaultdict(lambda: collections.Counter())
mbmj_titles = collections.Counter()
mbmj_codes = collections.Counter()

for cat in cats:
    # ---------- MBMJTBL ----------
    raw = get(iso, f'/{cat}/MBMJTBL.CD')
    recs = chain(raw)
    if recs is None:
        stats['MBMJTBL']['chain_fail'] += 1
    else:
        stats['MBMJTBL']['catalogs_ok'] += 1
        stats['MBMJTBL']['records'] += len(recs)
        mfiles = {p.split('/')[-1].upper() for p in files
                  if p.startswith(f'/{cat}/M/')}
        for r in recs:
            ln = len(r)
            if (ln - 34) % 10 != 0 or ln < 44:
                stats['MBMJTBL']['bad_record_len'] += 1
                continue
            code = r[2:4].decode('ascii', errors='replace')
            title = r[4:34].decode('cp932', errors='replace').strip()
            mbmj_codes[code] += 1
            mbmj_titles[title] += 1
            n = (ln - 34) // 10
            stats['MBMJTBL']['page_files'] += n
            for i in range(n):
                fc = r[34+i*10:34+(i+1)*10].decode('ascii', errors='replace').strip()
                # ファイルコード 4JSA71001 -> 実ファイル 4JSA7100.1
                cand = fc[:-1] + '.' + fc[-1]
                if cand in mfiles:
                    stats['MBMJTBL']['filecode_hit'] += 1
                else:
                    stats['MBMJTBL']['filecode_miss'] += 1
                    if stats['MBMJTBL']['filecode_miss'] <= 5:
                        print('  MBMJ miss:', cat, code, title, fc, cand)
        # Mフォルダの全ファイルが目次から参照されるか
        referenced = set()
        for r in recs:
            n = (len(r) - 34) // 10
            for i in range(n):
                fc = r[34+i*10:34+(i+1)*10].decode('ascii', errors='replace').strip()
                referenced.add(fc[:-1] + '.' + fc[-1])
        stats['MBMJTBL']['mfiles_total'] += len(mfiles)
        stats['MBMJTBL']['mfiles_referenced'] += len(mfiles & referenced)
        if mfiles - referenced:
            stats['MBMJTBL']['catalogs_with_unreferenced'] += 1
            if stats['MBMJTBL']['catalogs_with_unreferenced'] <= 3:
                print('  MBMJ unreferenced:', cat, sorted(mfiles - referenced))

    # ---------- PLCKTBL ----------
    raw = get(iso, f'/{cat}/PLCKTBL.CD')
    if len(raw) % 20 != 0:
        stats['PLCKTBL']['bad_len'] += 1
    else:
        stats['PLCKTBL']['catalogs_ok'] += 1
        n = len(raw) // 20
        stats['PLCKTBL']['slots'] += n
        for i in range(n):
            slot = raw[i*20:(i+1)*20].decode('cp932', errors='replace').strip()
            if slot.startswith('(') and slot.endswith(')'):
                stats['PLCKTBL']['paren_terms'] += 1
            else:
                stats['PLCKTBL']['non_paren'] += 1
                if stats['PLCKTBL']['non_paren'] <= 5:
                    print('  PLCK non-paren:', cat, repr(slot))

    # ---------- PLGKTBL ----------
    raw = get(iso, f'/{cat}/PLGKTBL.CD')
    if len(raw) % 17 != 0:
        stats['PLGKTBL']['bad_len'] += 1
    else:
        stats['PLGKTBL']['catalogs_ok'] += 1
        patA = re.compile(rb'^([A-Z0-9]{1,4}) +(\d{7})$')
        patB = re.compile(rb'^([A-Z0-9]{1,4}) (\d{7}) (\d{7}| {7})$')
        for i in range(0, len(raw), 17):
            r = raw[i:i+17]
            stats['PLGKTBL']['records'] += 1
            if patB.match(r):
                stats['PLGKTBL']['typeB'] += 1
            elif patA.match(r):
                stats['PLGKTBL']['typeA'] += 1
            else:
                stats['PLGKTBL']['unknown'] += 1
                if stats['PLGKTBL']['unknown'] <= 5:
                    print('  PLGK unknown:', cat, repr(r))

    # ---------- KCMST ----------
    raw = get(iso, f'/{cat}/KCMST.CD')
    recs = chain(raw)
    if recs is None:
        stats['KCMST']['chain_fail'] += 1
    else:
        stats['KCMST']['catalogs_ok'] += 1
        for r in recs:
            stats['KCMST']['records'] += 1
            if (len(r) - 57) % 60 != 0 or len(r) < 57:
                stats['KCMST']['bad_record_len'] += 1
                continue
            val = r[52:57].decode('ascii', errors='replace').strip()
            if re.fullmatch(r'\d+\.\d+', val):
                stats['KCMST']['value_numeric'] += 1
            elif val == '-':
                stats['KCMST']['value_dash'] += 1
            elif re.fullmatch(r'#\d+\.\d+', val):
                stats['KCMST']['value_hash'] += 1
            else:
                stats['KCMST']['value_other'] += 1
                if stats['KCMST']['value_other'] <= 8:
                    print('  KCMST other value:', cat, repr(val), repr(r[2:52]))

    # ---------- IBHTBL ----------
    raw = get(iso, f'/{cat}/IBHTBL.CD') if f'/{cat}/IBHTBL.CD' in files else None
    if raw is None:
        stats['IBHTBL']['absent'] += 1
    else:
        recs = chain(raw)
        if recs is None:
            stats['IBHTBL']['chain_fail'] += 1
        else:
            stats['IBHTBL']['catalogs_ok'] += 1
            for r in recs:
                stats['IBHTBL']['records'] += 1
                field = r[2:12]
                if field != b' ' * 10:
                    stats['IBHTBL']['field_nonspace'] += 1
                    if stats['IBHTBL']['field_nonspace'] <= 8:
                        print('  IBH nonspace field:', cat, repr(field), repr(r))
                seg = struct.unpack_from('<H', r, 12)[0]
                letters = r[14:]
                if seg != len(letters) + 2:
                    stats['IBHTBL']['seg_mismatch'] += 1
                if not re.fullmatch(rb'[A-Z]*', letters):
                    stats['IBHTBL']['letters_nonAZ'] += 1
                    if stats['IBHTBL']['letters_nonAZ'] <= 5:
                        print('  IBH letters:', cat, repr(letters))
                if letters != bytes(sorted(letters)):
                    stats['IBHTBL']['letters_unsorted'] += 1
                stats['IBHTBL']['alphabet'] += len(set(letters))

for name in ['MBMJTBL', 'PLCKTBL', 'PLGKTBL', 'KCMST', 'IBHTBL']:
    print()
    print(f'===== {name} =====')
    for k, v in sorted(stats[name].items()):
        print(f'  {k}: {v}')

print()
print('MBMJTBL page codes:', dict(mbmj_codes))
print('MBMJTBL titles (distinct):')
for t, c in mbmj_titles.most_common():
    print(f'  x{c}: {t}')
iso.close()
