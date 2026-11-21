#!/usr/bin/env python3
"""D班 データ突合: 項目1b (KCMST図単位), 項目2 (BLKTYTBL第1リスト),
項目3 (IBHTBL第1節), 項目4 (PLGKTBL キーC)。

ISO から KCMST / IBHTBL / PLGKTBL を全カタログ抽出し、
BLKTYTBL (analysis/work/<cat>/) と epc_index.sqlite と突合する。
結果は標準出力（要約）と analysis/work/d_data.json に出す。
"""
import io
import json
import os
import sqlite3
import struct
import sys
from collections import Counter, defaultdict

BASE = os.path.expanduser('~/workspace/epc-project')
sys.path.insert(0, os.path.join(BASE, 'analysis'))
sys.path.insert(0, os.path.join(BASE, 'converter'))
import iso_index  # noqa: E402
from epcconv.parsers import parse_plmst, parse_figkey  # noqa: E402

WD = os.path.join(BASE, 'analysis/work_d')
os.makedirs(WD, exist_ok=True)
WORK = os.path.join(BASE, 'analysis/work')

iso = iso_index.open_iso()
files = iso_index.load()
CATS = sorted({p.split('/')[1] for p in files
               if p.count('/') >= 2 and not p.startswith('/PROGRAM')})
CATS = [c for c in CATS
        if c and os.path.isdir(os.path.join(BASE, 'analysis/work', c))]


def get(cat, name):
    return iso_index.get(iso, f'/{cat}/{name}')


# ---------------- BLKTYTBL ----------------

def parse_blkty(data):
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        fk = rec[2:9].decode('ascii', 'replace')
        key = (fk[0:3].strip(), fk[3:5].strip(), fk[5:7].strip())
        po, pl, ko, kl = struct.unpack_from('<IIII', rec, 69)
        (l1,) = struct.unpack_from('<H', rec, 85)
        list1 = [struct.unpack_from('<H', rec, j)[0]
                 for j in range(87, 87 + l1, 2)]
        list2 = [struct.unpack_from('<H', rec, j)[0]
                 for j in range(87 + l1, len(rec) - 1, 2)]
        recs.append({'key': key, 'po': po, 'pl': pl, 'ko': ko, 'kl': kl,
                     'list1': list1, 'list2': list2})
        off += ln
    return recs


# ---------------- KCMST ----------------

def parse_kcmst(data):
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        name = rec[2:52].decode('cp932', 'replace').strip()
        val = rec[52:57].decode('ascii', 'replace').strip()
        recs.append({'name': name, 'val': val, 'off': off})
        off += ln
    return recs


# ---------------- IBHTBL ----------------

def parse_ibhtbl(data):
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        key = rec[2:12].decode('ascii', 'replace').strip()
        (cnt,) = struct.unpack_from('<H', rec, 12)
        chars = rec[14:].decode('ascii', 'replace')
        recs.append({'key': key, 'cntfield': cnt, 'chars': chars})
        off += ln
    return recs


# ---------------- PLGKTBL ----------------

def parse_plgk(data):
    out = []
    for i in range(0, len(data) - 16, 17):
        rec = data[i:i + 17]
        out.append({'key': chr(rec[0]),
                    'from': rec[1:9].decode('ascii', 'replace').strip(),
                    'to': rec[9:17].decode('ascii', 'replace').strip()})
    return out


result = {}

# ============ 項目1b: KCMST 図単位で値が決まるか ============
agg = Counter()
name_fig_values = defaultdict(lambda: defaultdict(set))  # cat -> name -> fig -> vals (global agg below)
global_multi = 0
multi_names = 0
resolved_by_fig = 0
still_multi_in_fig = 0
cross_fig_diff = 0
examples = []
for cat in CATS:
    try:
        blk = parse_blkty(open(os.path.join(WORK, cat, 'BLKTYTBL.CD'), 'rb').read())
        kc = parse_kcmst(get(cat, 'KCMST.CD'))
    except Exception as e:
        agg[f'skip_{cat}'] = str(e)[:50]
        continue
    # figure -> KCMST records in slice
    fig_of_rec = {}
    for b in blk:
        for r in kc:
            if b['ko'] <= r['off'] < b['ko'] + b['kl']:
                fig_of_rec[r['off']] = b['key']
    name_global = defaultdict(set)
    name_per_fig = defaultdict(lambda: defaultdict(set))
    for r in kc:
        name_global[r['name']].add(r['val'])
        f = fig_of_rec.get(r['off'])
        if f is not None:
            name_per_fig[r['name']][f].add(r['val'])
    for name, vals in name_global.items():
        if len(vals) > 1:
            multi_names += 1
            per = name_per_fig.get(name, {})
            if per and all(len(v) == 1 for v in per.values()):
                resolved_by_fig += 1
                singles = {next(iter(v)) for v in per.values()}
                if len(singles) > 1:
                    cross_fig_diff += 1
                    if len(examples) < 8:
                        examples.append((cat, name, sorted(vals),
                                         {str(k): sorted(v) for k, v in list(per.items())[:4]}))
            else:
                still_multi_in_fig += 1
result['kcmst_fig'] = {
    'multi_value_names_total': multi_names,
    'resolved_to_single_within_every_figure': resolved_by_fig,
    'still_multi_within_a_figure': still_multi_in_fig,
    'of_resolved_figure_dependent_value': cross_fig_diff,
    'examples': examples,
}
print('== 項目1b KCMST ==')
print(json.dumps(result['kcmst_fig'], ensure_ascii=False, indent=1)[:3000])

# ============ 項目2: BLKTYTBL 第1リスト ============
db = sqlite3.connect(os.path.join(BASE, 'epc_index.sqlite'))
# figure -> per-part code sets (from parts2 gjson)
fig_parts = defaultdict(list)   # (cat, block, figure, sub) -> [set(codes)]
for cat, block, figure, sub, gjson in db.execute(
        'SELECT catalog, block, figure, sub, gjson FROM parts2'):
    groups = json.loads(gjson)
    s = set()
    for _q, codes in groups:
        s.update(codes)
    fig_parts[(cat, block, figure, sub)].append(s)
# models per catalog: ids
models = defaultdict(list)
for cat, ids in db.execute('SELECT catalog, ids FROM models'):
    if ids:
        models[cat].append([int(x) for x in ids.split(',') if x.strip()])
# hotspots per figure
figmap = {}
try:
    for cat, subdir, fn, hs in db.execute(
            'SELECT catalog, subdir, filename, hotspots FROM figures'):
        figmap[(cat, subdir, fn)] = hs
except Exception as e:
    print('figures table issue:', e)

hyp = Counter()
len_corr = defaultdict(list)  # feature -> list of (|A|, feature)
for cat in CATS:
    blk = parse_blkty(open(os.path.join(WORK, cat, 'BLKTYTBL.CD'), 'rb').read())
    subs_count = Counter((b['key'][0], b['key'][1]) for b in blk)
    cat_models = models.get(cat, [])
    first_ids = {m[0] for m in cat_models}
    for b in blk:
        key = (cat,) + b['key']
        A = set(b['list1'])
        L2 = set(b['list2'])
        parts = fig_parts.get(key, [])
        U = set().union(*parts) if parts else set()
        I = set.intersection(*parts) if parts else set()
        pats = {frozenset(s) for s in parts}
        hyp['total'] += 1
        if A <= L2:
            hyp['A_subset_L2'] += 1
        if A <= U:
            hyp['A_subset_U'] += 1
        if A <= I:
            hyp['A_subset_I'] += 1
        if A and A <= (U - I):
            hyp['A_subset_UminusI'] += 1
        if A == (U - L2):
            hyp['A_eq_UminusL2'] += 1
        if A == (L2 - I):
            hyp['A_eq_L2minusI'] += 1
        if A == (U - I):
            hyp['A_eq_UminusI'] += 1
        cand = {m[0] for m in cat_models if set(m) & U}
        if A == cand:
            hyp['A_eq_firstids_of_applicable_models'] += 1
        if A <= first_ids:
            hyp['A_subset_firstids'] += 1
        len_corr['n_subs'].append((len(A), subs_count[(b['key'][0], b['key'][1])]))
        len_corr['n_patterns'].append((len(A), len(pats)))
        len_corr['n_parts'].append((len(A), len(parts)))
        len_corr['union_size'].append((len(A), len(U)))
        len_corr['list2_size'].append((len(A), len(L2)))
result['blkty_list1'] = {'hypotheses': dict(hyp)}
print('== 項目2 BLKTYTBL第1リスト 仮説検証 ==')
print(dict(hyp))
for feat, pairs in len_corr.items():
    same = sum(1 for a, f in pairs if a == f)
    print(f'  |A| == {feat}: {same}/{len(pairs)}')

# ============ 項目3: IBHTBL 第1節 ============
ibh = {}
for cat in CATS:
    try:
        recs = parse_ibhtbl(get(cat, 'IBHTBL.CD'))
    except Exception:
        continue
    s1 = [r for r in recs if not r['key']]
    s2 = [r for r in recs if r['key']]
    ibh[cat] = (s1, s2)
cntfield_vals = Counter()
for cat, (s1, s2) in ibh.items():
    for r in s2:
        cntfield_vals[r['cntfield']] += 1
print('== 項目3 IBHTBL ==')
print('第2節 [12:14] フィールド値の分布:', dict(cntfield_vals))
# PLMST suffix characters per catalog (12th char of raw partno field)
suf = {}
for cat in CATS:
    pdata = open(os.path.join(BASE, 'cd/plmst_all', f'{cat}_PLMST.CD'), 'rb').read()
    chars = Counter()
    for (_fk, pn, _nm, _pr, _tail) in parse_plmst(pdata):
        if len(pn) >= 12 and pn[11] != ' ':
            chars[pn[11]] += 1
    suf[cat] = set(chars)
match_stats = Counter()
for cat, (s1, s2) in ibh.items():
    u1 = set().union(*[set(r['chars']) for r in s1]) if s1 else set()
    s2letters = set(''.join(r['key'] for r in s2))
    match_stats['cats'] += 1
    if u1 == suf.get(cat, set()):
        match_stats['S1union_eq_PLMST_suffix_chars'] += 1
    if u1 <= suf.get(cat, set()):
        match_stats['S1union_subset_suffix'] += 1
    if u1 == s2letters:
        match_stats['S1union_eq_S2key_letters'] += 1
    if cat == '11SA702':
        result['ibh_city'] = {
            's1_charsets': [r['chars'] for r in s1],
            's1_union': ''.join(sorted(u1)),
            'plmst_suffix_chars': ''.join(sorted(suf.get(cat, set()))),
            's2_key_letters': ''.join(sorted(s2letters)),
            's2_keys': [r['key'] for r in s2],
        }
print(dict(match_stats))
print(json.dumps(result.get('ibh_city', {}), ensure_ascii=False, indent=1))

# ============ 項目4: PLGKTBL キーC ============
c_cats = ['1168005', '11SB001', '11SB601', '11SC902', '11SD501', '11SD511',
          '11SF101', '11SH201', '11SH301', '11SH401', '11SH501', '11SJ701']
c_info = {}
for cat in c_cats:
    recs = parse_plgk(get(cat, 'PLGKTBL.CD'))
    crec = [r for r in recs if r['key'] == 'C']
    names = db.execute(
        'SELECT DISTINCT name, type_full, engine FROM models WHERE catalog=?',
        (cat,)).fetchall()
    c_info[cat] = {
        'c_count': len(crec),
        'c_samples': crec[:6],
        'other_keys': dict(Counter(r['key'] for r in recs)),
        'models_sample': names[:6],
    }
result['plgk_c'] = c_info
print('== 項目4 PLGKTBL C ==')
print(json.dumps(c_info, ensure_ascii=False, indent=1)[:4000])

json.dump(result, open(os.path.join(BASE, 'analysis/work/d_data.json'), 'w'),
          ensure_ascii=False, indent=1)
iso.close()
print('saved analysis/work/d_data.json')
