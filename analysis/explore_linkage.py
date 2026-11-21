#!/usr/bin/env python3
"""B班 探索8: KCMST-PLMST対応付け規則 / IBHTBLキーとIMTBL照合 / PLGK号機帯とモデル範囲"""
import struct, re, sys, os, collections, sqlite3, unicodedata
sys.path.insert(0, os.path.dirname(__file__))
from iso_index import load, open_iso, get

files = load()
iso = open_iso()

def chain(data):
    off = 0; recs = []
    while off < len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < 2 or off + ln > len(data):
            return None
        recs.append(data[off:off+ln]); off += ln
    return recs

print('===== IBHTBL 第2セクションのキー vs ルート IMTBL.CD =====')
imtbl = get(iso, '/IMTBL.CD')
imtbl_txt = imtbl.decode('cp932', errors='replace')
hit = 0; tot = 0; miss = []
for cat in sorted({p.split('/')[1] for p in files if f"/{p.split('/')[1]}/PLMST.CD" in files}):
    if f'/{cat}/IBHTBL.CD' not in files:
        continue
    for r in chain(get(iso, f'/{cat}/IBHTBL.CD')):
        key = r[2:12].decode('ascii', errors='replace').strip()
        if key:
            tot += 1
            # IMTBL はコードが先頭フィールド。部分一致でなく単語境界っぽく探す
            if key in imtbl_txt:
                hit += 1
            else:
                miss.append((cat, key))
print(f'color-code keys: {tot}, found in IMTBL text: {hit}, miss: {len(miss)}')
print('miss examples:', miss[:15])

print()
print('===== KCMST 対応付け: PLMST名のベース名化で一致率が上がるか (11SA702) =====')
db = sqlite3.connect(os.path.expanduser('~/workspace/epc-project/epc_index.sqlite'))
rows = db.execute("SELECT name FROM parts WHERE catalog='11SA702' ORDER BY rowid").fetchall()
plmst_raw = [unicodedata.normalize('NFKC', n).strip() for (n,) in rows]

def basename(n):
    # 先頭の1文字コード (例 'A' + 本名) を除去、*色コード* と (注記) を除去
    s = n
    s = re.sub(r'\*[^*]*\*', '', s)          # *NH1L* 等
    s = re.sub(r'\([^)]*\)', '', s)           # (DENSO) 等
    s = re.sub(r'\s+', ' ', s).strip()
    # 先頭の単独大文字1字 + 後続 (色/タイプ区分の接頭辞と推定)
    s = re.sub(r'^[A-Z](?=[\u3040-\u30ff])', '', s)
    return s.strip()

plmst_base = [basename(n) for n in plmst_raw]
plmst_base_set = set(plmst_base)
kc_recs = chain(open(os.path.expanduser('~/workspace/epc-project/cd/extracted/11SA702/KCMST.CD'), 'rb').read())
kc_names = [r[2:52].decode('cp932', errors='replace').strip() for r in kc_recs]
kc_nfkc = [unicodedata.normalize('NFKC', n).strip() for n in kc_names]
kc_set = set(kc_nfkc)
print('KCMST unique names:', len(kc_set))
print('match vs PLMST base names:', len(kc_set & plmst_base_set),
      f"= {len(kc_set & plmst_base_set)/len(kc_set)*100:.1f}%")
print('PLMST base names covered:', len(kc_set & plmst_base_set), '/', len(plmst_base_set),
      f"= {len(kc_set & plmst_base_set)/len(plmst_base_set)*100:.1f}%")
print('KCMST names still unmatched (first 15):')
for n in sorted(kc_set - plmst_base_set)[:15]:
    print('   ', n)

print()
print('===== KCMST 並び順: PLMST初出順と単調か =====')
first_idx = {}
for i, b in enumerate(plmst_base):
    first_idx.setdefault(b, i)
seq = [first_idx.get(n) for n in kc_nfkc]
known = [(i, v) for i, v in enumerate(seq) if v is not None]
inversions = sum(1 for a, b in zip(known, known[1:]) if b[1] < a[1])
print(f'KCMST entries with PLMST match: {len(known)}/{len(seq)}, adjacent inversions: {inversions}')
# 重複名エントリの値の違い
byname = collections.defaultdict(list)
for r, n in zip(kc_recs, kc_nfkc):
    byname[n].append(r[52:57].decode('ascii', errors='replace').strip())
dups = {k: v for k, v in byname.items() if len(v) > 1}
print('dup-name entries:', len(dups), 'examples:')
for k, v in list(dups.items())[:10]:
    print('   ', k, v)

print()
print('===== KCMST 値なしエントリの例 =====')
cnt = 0
for cat in sorted({p.split('/')[1] for p in files if f"/{p.split('/')[1]}/PLMST.CD" in files}):
    for r in chain(get(iso, f'/{cat}/KCMST.CD')):
        if r[52:57].strip() == b'':
            print('  ', cat, r[2:52].decode('cp932', errors='replace').strip())
            cnt += 1
            if cnt >= 6: break
    if cnt >= 6: break

print()
print('===== PLGKTBL 号機帯 vs モデル号機範囲 (11SA702 / 11SC701) =====')
for cat in ['11SA702', '11SC701']:
    ms = db.execute("SELECT serial_from, serial_to FROM models WHERE catalog=?", (cat,)).fetchall()
    bands = sorted({(f, t) for f, t in ms})
    print(cat, 'models:', len(ms), 'distinct bands:', bands[:12])
    raw = get(iso, f'/{cat}/PLGKTBL.CD')
    vals = set()
    for i in range(0, len(raw), 17):
        r = raw[i:i+17]
        for fld in (r[1:9], r[9:17]):
            s = fld.decode('ascii', errors='replace').strip()
            if s:
                vals.add(s)
    print('  PLGK distinct values:', len(vals), ' sample:', sorted(vals)[:8])
iso.close()
