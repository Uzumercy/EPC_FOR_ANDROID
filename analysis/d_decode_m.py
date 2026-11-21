#!/usr/bin/env python3
"""D班: Mフォルダ前文ページを指定カタログ×ページコードでデコードして PNG 保存する。

使い方: d_decode_m.py CAT:PAGE [CAT:PAGE ...]
例: d_decode_m.py 11SA702:90 11SB001:10 11S0601:20
保存先: analysis/work/d_pages/<CAT>_<file>.png
"""
import io
import os
import struct
import sys

BASE = os.path.expanduser('~/workspace/epc-project')
sys.path.insert(0, os.path.join(BASE, 'analysis'))
sys.path.insert(0, os.path.join(BASE, 'converter'))
import iso_index  # noqa: E402
from epcconv.parsers import figure_segments, make_tiff  # noqa: E402
from PIL import Image  # noqa: E402

OUT = os.path.join(BASE, 'analysis/work/d_pages')
os.makedirs(OUT, exist_ok=True)
iso = iso_index.open_iso()


def parse_mbmj(data):
    pages = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        rec = data[off:off + ln]
        code = rec[2:4].decode('ascii', 'replace')
        title = rec[4:34].decode('cp932', 'replace').strip()
        codes = [rec[i:i + 10].decode('ascii', 'replace').strip()
                 for i in range(34, ln - 9, 10)]
        pages.append((code, title, [c for c in codes if c]))
        off += ln
    return pages


def decode(data):
    for off, ln, t in figure_segments(data):
        if t in ('2', '3'):
            w, h = struct.unpack_from('>HH', data, off + 11)
            img = Image.open(io.BytesIO(make_tiff(data[off + 21:off + ln], w, h)))
            img.load()
            return img
    return None


for arg in sys.argv[1:]:
    cat, page = arg.split(':')
    mbmj = parse_mbmj(iso_index.get(iso, f'/{cat}/MBMJTBL.CD'))
    # M フォルダの実ファイル一覧
    import pycdlib  # noqa
    mfiles = []
    for _dn, _dl, fl in iso.walk(iso_path=f'/{cat}/M'):
        mfiles = fl
    by_stripped = {f.replace('.', '').replace(';1', ''): f for f in mfiles}
    for code, title, fcodes in mbmj:
        if code != page:
            continue
        print(f'{cat} page {code} {title}: {fcodes}')
        for fc in fcodes:
            fn = by_stripped.get(fc)
            if fn is None:
                print(f'  !! ファイルが見つからない: {fc}')
                continue
            data = iso_index.get(iso, f'/{cat}/M/{fn}')
            img = decode(data)
            outp = os.path.join(OUT, f'{cat}_{fn}.png')
            img.save(outp)
            print(f'  -> {outp} ({img.size[0]}x{img.size[1]})')
iso.close()
