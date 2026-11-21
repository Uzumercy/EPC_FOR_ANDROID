#!/usr/bin/env python3
"""ISOの全ファイル一覧を索引化して analysis/iso_index.json に保存/再利用する"""
import pycdlib, os, io, json

ISO = os.path.expanduser('~/workspace/epc-project/cd/HONDA_EPC.ISO')
IDX = os.path.expanduser('~/workspace/epc-project/analysis/iso_index.json')

def build():
    iso = pycdlib.PyCdlib()
    iso.open(ISO)
    files = {}  # path -> size
    for dirname, dirlist, filelist in iso.walk(iso_path='/'):
        for f in filelist:
            p = (dirname + '/' + f).upper()
            # サイズ取得
            try:
                rec = iso.get_record(iso_path=p)
                files[p] = rec.data_length
            except Exception:
                files[p] = None
    iso.close()
    json.dump(files, open(IDX, 'w'))
    return files

def load():
    if os.path.exists(IDX):
        return json.load(open(IDX))
    return build()

def open_iso():
    iso = pycdlib.PyCdlib()
    iso.open(ISO)
    return iso

def get(iso, path):
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=path.upper())
    return buf.getvalue()

if __name__ == '__main__':
    files = build()
    print('total files:', len(files))
    cats = sorted({p.split('/')[1] for p in files if p.count('/') >= 2 and not p.startswith('/PROGRAM')})
    print('top-level dirs (excl PROGRAM):', len(cats))
    sa = {p: s for p, s in files.items() if p.startswith('/11SA702/')}
    cdsum = sum(s for p, s in sa.items() if p.endswith('.CD'))
    fig = {p: s for p, s in sa.items() if not p.endswith('.CD')}
    print('11SA702 .CD total:', cdsum)
    print('11SA702 non-CD (figures) total:', sum(fig.values()), 'count', len(fig))
    mfig = {p: s for p, s in fig.items() if '/M/' in p}
    print('11SA702 M figures:', sum(mfig.values()), 'count', len(mfig))
    print('11SA702 figures 1-7:', sum(s for p, s in fig.items() if '/M/' not in p))
