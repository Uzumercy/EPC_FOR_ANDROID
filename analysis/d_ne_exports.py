#!/usr/bin/env python3
"""D班 項目5: fd/exp7z の 16bit NE バイナリのエクスポート/インポート表を解析する。

NE ヘッダをパースし、以下をファイル別にダンプする:
- モジュール名（resident names 先頭）
- エクスポート名（resident + nonresident names のうち ordinal を持つもの）
- インポートモジュール名（imported names table に現れる DLL 名）
"""
import os
import struct

EXP = os.path.expanduser("~/workspace/epc-project/fd/exp7z")
EXTRA = [os.path.expanduser("~/workspace/epc-project/cd/program/exp/HMEPCBHN.DLl"), os.path.expanduser("~/workspace/epc-project/cd/program/HMEPCAT.EXE")]


def parse_ne(path):
    d = open(path, 'rb').read()
    if d[:2] != b'MZ':
        return None
    (e_lfanew,) = struct.unpack_from('<I', d, 0x3c)
    if d[e_lfanew:e_lfanew + 2] != b'NE':
        return {'error': f'not NE (sig={d[e_lfanew:e_lfanew+2]!r})'}
    ne = e_lfanew
    # NE header fields (offsets relative to ne header start)
    (cseg, modref_count, _nres_size) = struct.unpack_from('<HHH', d, ne + 0x1c)
    (seg_table_off, _resrc_off, resname_off, modref_off, impname_off) = \
        struct.unpack_from('<HHHHH', d, ne + 0x22)
    (nresname_off,) = struct.unpack_from('<I', d, ne + 0x2c)
    seg_table = ne + seg_table_off
    resname_table = ne + resname_off
    modref_table = ne + modref_off
    impname_table = ne + impname_off

    def read_names(off, limit):
        """length-prefixed name + u16 ordinal の列を読む。ordinal=0 はモジュール名等。"""
        out = []
        p = off
        while p < limit:
            ln = d[p]
            if ln == 0:
                break
            name = d[p + 1:p + 1 + ln].decode('ascii', 'replace')
            (ordv,) = struct.unpack_from('<H', d, p + 1 + ln)
            out.append((name, ordv))
            p += 1 + ln + 2
        return out

    # resident names: テーブル終端は次のテーブル開始位置のうち最小のもの
    ends = [x for x in (seg_table, modref_table, impname_table, len(d)) if x > resname_table]
    resident = read_names(resname_table, min(ends))
    module_name = resident[0][0] if resident else '?'
    exports = [n for n, o in resident if o != 0]
    # nonresident names
    nonres = read_names(nresname_off, len(d)) if nresname_off else []
    exports += [n for n, o in nonres if o != 0]
    # imports: module references -> imported names table のオフセット列
    imports = []
    for i in range(modref_count):
        (off,) = struct.unpack_from('<H', d, modref_table + 2 * i)
        p = impname_table + off
        ln = d[p]
        imports.append(d[p + 1:p + 1 + ln].decode('ascii', 'replace'))
    return {'module': module_name, 'exports': exports, 'imports': imports,
            'segments': cseg}


for b in sorted(os.listdir(EXP)) + EXTRA:
    r = parse_ne(b if os.path.isabs(b) else os.path.join(EXP, b))
    print(f'===== {b}')
    if r is None:
        print('  (not MZ)')
        continue
    if 'error' in r:
        print(' ', r['error'])
        continue
    print(f"  module={r['module']} segments={r['segments']}")
    print(f"  imports: {', '.join(r['imports'])}")
    print(f"  exports ({len(r['exports'])}):")
    for e in r['exports']:
        print(f'    {e}')
