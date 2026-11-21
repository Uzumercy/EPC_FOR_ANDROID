#!/usr/bin/env python3
"""D班 項目5: Win16 メニューリソース (RT_MENU) の項目テキスト抽出。
d_resources.py の Res / parse_menu を再利用する。
注意: HMEPC.EXe ではダイアログとメニューでリソースオフセットの基準が異なり、
メニューは base=0 で読む（ダイアログは NE ヘッダ基準で読める場合がある）。
結果は analysis/work/d_menus.txt。
"""
import glob
import os
import sys

BASE = os.path.expanduser('~/workspace/epc-project')
sys.path.insert(0, os.path.join(BASE, 'analysis'))
from d_resources import Res, parse_menu, RT_MENU  # noqa: E402

OUT = os.path.join(BASE, 'analysis/work/d_menus.txt')

lines = []
targets = sorted(glob.glob(os.path.join(BASE, 'fd/exp7z/*')) +
                 glob.glob(os.path.join(BASE, 'cd/program/exp/*')))
for path in targets:
    if not os.path.isfile(path):
        continue
    data = open(path, 'rb').read()
    try:
        r = Res(data)
        ents = r.entries()
    except Exception:
        continue
    for (t, rid, off, ln) in ents:
        if t != RT_MENU:
            continue
        try:
            txts = parse_menu(data, off, ln)
        except Exception:
            continue
        if txts:
            lines.append(f'== {os.path.basename(path)} MENU {rid}')
            lines.extend('   ' + x for x in txts)
open(OUT, 'w', encoding='utf-8').write('\n'.join(lines))
print(f'{len(lines)} lines -> {OUT}')
