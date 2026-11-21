#!/usr/bin/env python3
"""B班 探索4: ISOから他カタログのファイルを取り出し比較する土台 + 図ファイル合計"""
import pycdlib, os, sys, collections

ISO = os.path.expanduser('~/workspace/epc-project/cd/HONDA_EPC.ISO')
iso = pycdlib.PyCdlib()
iso.open(ISO)

catalogs = []
for d in iso.list_children(iso_path='/'):
    name = d.file_identifier().decode('ascii', errors='replace').rstrip(';1')
    if name not in ('.', '..', 'PROGRAM'):
        catalogs.append(name)
catalogs.sort()
print('catalogs:', len(catalogs))

def get(cat, fn):
    try:
        import io
        buf = io.BytesIO()
        iso.get_file_from_iso_fp(buf, iso_path=f'/{cat}/{fn}')
        return buf.getvalue()
    except Exception:
        return None

def listdir(cat, sub=None):
    p = f'/{cat}' + (f'/{sub}' if sub else '')
    out = []
    try:
        for d in iso.list_children(iso_path=p):
            nm = d.file_identifier().decode('ascii', errors='replace').rstrip(';1')
            if nm in ('.', '..'):
                continue
            out.append((nm, d.data_length, d.is_directory()))
    except Exception as e:
        return None
    return out

if __name__ == '__main__':
    # 11SA702 の全ファイルサイズと図サブディレクトリ合計
    tot_all = 0; tot_fig = 0; tot_figM = 0
    for nm, ln, isdir in listdir('11SA702'):
        if not isdir:
            tot_all += ln
    for sub in ['1', '2', '3', '4', '5', '6', '7', 'M']:
        files = listdir('11SA702', sub)
        s = sum(ln for nm, ln, isdir in files if not isdir)
        print(f'subdir {sub}: {len([f for f in files if not f[2]])} files, {s} bytes')
        tot_fig += s
        if sub == 'M':
            tot_figM = s
    print('catalog .CD total:', tot_all)
    print('figures total (1-7+M):', tot_fig, ' M only:', tot_figM, ' 1-7:', tot_fig - tot_figM)
    print('PLBTBLJH first/last u32 candidates: 13107632 / 13501557')
