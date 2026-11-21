#!/usr/bin/env python3
"""D班 項目5: FD側展開済みバイナリ fd/exp7z/ に対する文字列走査。

- 各バイナリがどの .CD ファイル名（ルート11種＋カタログ内14種）を
  バイト列として含むかを全数マッピングする。
- あわせて、各バイナリ内の ".CD" を含む ASCII 文字列を全部抜き出す。
- NE のエクスポート名らしき文字列（大文字英数字+アンダースコアの長い語）も
  ファイル別に集計する（別スクリプトで詳細を見るための索引）。
結果は標準出力に表形式で出す。
"""
import os
import re
from collections import defaultdict

EXP = os.path.expanduser('~/workspace/epc-project/fd/exp7z')

ROOT_CD = ['KSRBHMH', 'SYSBMST', 'KRHHKI', 'KRHHDKI', 'TSMIR', 'IMTBL',
           'REUSE', 'HAMP', 'CDJHTBL', 'GRPBRTBL', 'HPLTBLJH']
CAT_CD = ['PLMST', 'GRPTBL', 'BLKTBL', 'BLKTYTBL', 'PLMSBBI1', 'PLMSBBI2',
          'PLMKSBI1', 'PLMKSBI2', 'PLGKTBL', 'PLCKTBL', 'KCMST', 'IBHTBL',
          'MBMJTBL', 'PLBTBLJH']
ALL_CD = ROOT_CD + CAT_CD

bins = sorted(os.listdir(EXP))
data = {}
for b in bins:
    with open(os.path.join(EXP, b), 'rb') as f:
        data[b] = f.read()

print('=== .CDファイル名の参照マップ（ファイル名＋".CD" の完全形で検索） ===')
print(f"{'CD file':12s} " + ' '.join(f'{b[:10]:>10s}' for b in bins))
for cd in ALL_CD:
    needle = (cd + '.CD').encode('ascii')
    row = []
    for b in bins:
        n = data[b].count(needle)
        row.append(f'{n:>10d}' if n else f'{"-":>10s}')
    print(f'{cd:12s} ' + ' '.join(row))

print()
print('=== 拡張子なしの基名だけでも現れるか（完全形が無い場合の補助） ===')
for cd in ALL_CD:
    needle_full = (cd + '.CD').encode('ascii')
    needle_base = cd.encode('ascii')
    for b in bins:
        nf = data[b].count(needle_full)
        nb = data[b].count(needle_base)
        if nb and not nf:
            print(f'{cd}: {b} base-only x{nb}')

print()
print('=== バイナリ別の ".CD" を含む ASCII 文字列（前後を含む抽出） ===')
pat = re.compile(rb'[\x20-\x7e]{4,}')
for b in bins:
    hits = []
    for m in pat.finditer(data[b]):
        s = m.group().decode('ascii', 'replace')
        if '.CD' in s.upper():
            hits.append((m.start(), s))
    print(f'--- {b} ({len(hits)} strings)')
    for off, s in hits:
        print(f'  @{off:#08x} {s!r}')
