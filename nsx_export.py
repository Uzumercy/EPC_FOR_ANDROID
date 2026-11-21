#!/usr/bin/env python3
"""Export all NSX parts figures (+ front matter) from the EPC ISOs to PNG.

Catalogs (identified from the 10Z model master, newest disc wins):
  11SL001 -> 21CD08X (only disc carrying it)
  11SW001 -> 21CD10Z (also on 08X, 10Z is newer)

Output: nsx-figures/<CAT>/<subdir>/<file>.png, per-catalog index.csv,
top-level index.txt, and nsx-figures.zip.  Existing app DB / packs /
converter outputs are not touched.
"""
import csv
import io
import os
import struct
import sys
import zipfile

BASE = os.path.expanduser('~/workspace/epc-project')
sys.path.insert(0, os.path.join(BASE, 'converter'))
from epcconv.parsers import figure_segments, make_tiff, parse_blkty  # noqa: E402
import pycdlib  # noqa: E402
from PIL import Image  # noqa: E402

TARGETS = {  # catalog -> (disc tag, iso path)
    '11SL001': ('21CD08X', os.path.join(BASE, 'cd2/21CD08X.iso')),
    '11SW001': ('21CD10Z', os.path.join(BASE, 'cd2/21CD10Z.iso')),
}
OUTROOT = os.path.join(BASE, 'nsx-figures')


def read_file(iso, path):
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=path)
    return buf.getvalue()


def list_dir(iso, path):
    for dirname, dirlist, filelist in iso.walk(iso_path=path):
        if dirname == path:
            return dirlist, [f.split(';')[0] for f in filelist]
    return [], []


def decode_png(data):
    """Decode the first image segment ('3' parts / '2' front matter)."""
    for off, ln, t in figure_segments(data):
        if t in ('2', '3'):
            w, h = struct.unpack_from('>HH', data, off + 11)
            img = Image.open(io.BytesIO(make_tiff(data[off + 21:off + ln], w, h)))
            img.load()
            return img, t, w, h
    return None, None, 0, 0


def parse_mbmj(data):
    """MBMJTBL.CD -> [(page_code, title, [file codes])]."""
    pages, off = [], 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < 34 or off + ln > len(data):
            break
        rec = data[off:off + ln]
        code = rec[2:4].decode('ascii', 'replace').strip()
        title = rec[4:34].decode('cp932', 'replace').strip()
        codes = [rec[i:i + 10].decode('ascii', 'replace').strip()
                 for i in range(34, ln - 9, 10)]
        pages.append((code, title, [c for c in codes if c]))
        off += ln
    return pages


def code_candidates(code):
    """Drawing code -> candidate figure filenames ('.' before last 1-3)."""
    out = [code]
    for k in (1, 2, 3):
        if len(code) > k:
            out.append(code[:-k] + '.' + code[-k:])
    return out


def main():
    os.makedirs(OUTROOT, exist_ok=True)
    summary = []
    total_figs = 0
    for cat, (tag, isopath) in sorted(TARGETS.items()):
        iso = pycdlib.PyCdlib()
        iso.open(isopath)
        catdir = f'/{cat}'
        subdirs, rootfiles = list_dir(iso, catdir)

        # --- decode every figure file, grouped by subdir -----------------
        decoded = {}   # (subdir, filename) -> png relpath
        segtypes = {}
        fails = []
        for sub in subdirs:
            files = list_dir(iso, f'{catdir}/{sub}')[1]
            for fn in files:
                data = read_file(iso, f'{catdir}/{sub}/{fn}')
                try:
                    img, t, w, h = decode_png(data)
                except Exception as ex:
                    img, t = None, None
                    fails.append((sub, fn, repr(ex)[:80]))
                if img is None:
                    if t is None and (sub, fn) not in [(s, f) for s, f, _ in fails]:
                        fails.append((sub, fn, 'no image segment'))
                    continue
                rel = f'{sub}/{fn}.png'
                outpath = os.path.join(OUTROOT, cat, rel)
                os.makedirs(os.path.dirname(outpath), exist_ok=True)
                img.save(outpath, optimize=True)
                decoded[(sub, fn)] = rel
                segtypes[(sub, fn)] = t
        n_parts = sum(1 for (s, _) in decoded if s != 'M')
        n_front = sum(1 for (s, _) in decoded if s == 'M')
        total_figs += len(decoded)

        # --- index from BLKTYTBL (parts figures) -------------------------
        blkty = read_file(iso, f'{catdir}/BLKTYTBL.CD')
        records, _methods = parse_blkty(blkty)
        by_name = {fn: (sub, rel) for (sub, fn), rel in decoded.items()}
        rows = []
        matched_files = set()
        for r in records:
            hit = None
            for cand in code_candidates(r['code']):
                if cand in by_name:
                    hit = by_name[cand]
                    break
            png = hit[1] if hit else ''
            if hit:
                matched_files.add((hit[0], cand))
            rows.append([r['block'], r['fig'], r['sub'], r['code'],
                         r['title'], png])
        unmatched = [(s, f) for (s, f) in decoded
                     if s != 'M' and (s, f) not in matched_files]

        # --- front matter index from MBMJTBL ------------------------------
        front_rows = []
        if 'MBMJTBL.CD' in rootfiles:
            pages = parse_mbmj(read_file(iso, f'{catdir}/MBMJTBL.CD'))
            mfiles = {fn.replace('.', ''): fn
                      for (s, fn) in decoded if s == 'M'}
            for pcode, title, fcodes in pages:
                for fc in fcodes:
                    fn = mfiles.get(fc.replace('.', ''))
                    front_rows.append([pcode, title, fc,
                                       f'M/{fn}.png' if fn else ''])

        with open(os.path.join(OUTROOT, cat, 'index.csv'), 'w',
                  newline='', encoding='utf-8') as fh:
            wtr = csv.writer(fh)
            wtr.writerow(['block', 'figure', 'sub', 'drawing_code',
                          'title', 'png'])
            wtr.writerows(rows)
            if front_rows:
                wtr.writerow([])
                wtr.writerow(['front_matter_page', 'title', 'file_code', 'png'])
                wtr.writerows([[p, t, fc, png] for p, t, fc, png in front_rows])

        iso.close()
        summary.append((cat, tag, len(records), n_parts, n_front,
                        len(front_rows), len(unmatched), fails))
        print(f'{cat} ({tag}): blkty={len(records)} parts_png={n_parts} '
              f'front_png={n_front} front_indexed={len(front_rows)} '
              f'unmatched_png={len(unmatched)} fails={len(fails)}')
        for u in unmatched[:10]:
            print('   unmatched:', u)
        for f in fails[:10]:
            print('   FAIL:', f)

    with open(os.path.join(OUTROOT, 'index.txt'), 'w', encoding='utf-8') as fh:
        fh.write('NSX 図集 export（ホンダEPC DISC2より）\n')
        fh.write('カタログ同定: 21CD10Z版モデルマスタで通称名にNSXを含むモデルを抽出\n')
        fh.write('採用版: 同じカタログが複数版にある場合は最新版（10Z > 08X > DISC1）\n\n')
        for cat, tag, nb, np_, nf, nfi, nu, fails in summary:
            fh.write(f'{cat}（{tag}より）: 部品図 {np_} 枚 / 前文 {nf} 枚 '
                     f'（Mフォルダ, index {nfi} 件）/ BLKTYTBL {nb} 件\n')
        fh.write(f'\n合計: {total_figs} 枚\n')
        fh.write('各カタログフォルダの index.csv に、ブロック番号・図番・'
                 '図面コード・タイトルとPNGファイル名の対応を収録。\n')
        fh.write('前文ページは各カタログの M サブフォルダに分離。\n')
    print(f'TOTAL PNGs: {total_figs}')

    zpath = os.path.join(BASE, 'nsx-figures.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(OUTROOT):
            for fn in files:
                p = os.path.join(root, fn)
                z.write(p, os.path.relpath(p, BASE))
    print(f'ZIP: {zpath} ({os.path.getsize(zpath):,} bytes)')


if __name__ == '__main__':
    main()
