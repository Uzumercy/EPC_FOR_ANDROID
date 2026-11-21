#!/usr/bin/env python3
"""D班 項目5（拡張）: NE バイナリのリソースからダイアログ／メニュー／文字列を抽出する。

各 EXE/DLL について:
- リソーステーブルの RT_DIALOG(5) / RT_MENU(4) / RT_STRING(6) を列挙
- ダイアログはキャプションとコントロールのテキスト（ラベル・ボタン名）を復元
- メニューは項目テキストを復元
- 文字列テーブルは ID 付きで復元
文字列は cp932 としてデコードする。
"""
import os
import struct
import sys

RT_MENU = 4
RT_DIALOG = 5
RT_STRING = 6

TARGETS = []
EXP = os.path.expanduser('~/workspace/epc-project/fd/exp7z')
for b in sorted(os.listdir(EXP)):
    TARGETS.append(os.path.join(EXP, b))
TARGETS.append(os.path.expanduser('~/workspace/epc-project/cd/program/exp/HMEPCBHN.DLl'))
TARGETS.append(os.path.expanduser('~/workspace/epc-project/cd/program/HMEPCAT.EXE'))


def dec(b):
    return b.decode('cp932', 'replace')


class Res:
    def __init__(self, data):
        self.d = data
        (self.lfanew,) = struct.unpack_from('<I', data, 0x3c)
        ne = self.lfanew
        assert data[ne:ne + 2] == b'NE'
        (self.rsrc_off,) = struct.unpack_from('<H', data, ne + 0x24)
        self.rsrc = ne + self.rsrc_off
        (self.shift,) = struct.unpack_from('<H', data, self.rsrc)

    def entries(self):
        """(type_id, res_id, offset, length) の列（offset/length はバイト単位に換算済み）"""
        d = self.d
        p = self.rsrc + 2
        out = []
        while True:
            (type_id, count) = struct.unpack_from('<HH', d, p)
            if type_id == 0:
                break
            p += 8  # type, count, reserved(4)
            for _ in range(count):
                off, ln, _flags, rid = struct.unpack_from('<HHHH', d, p)
                out.append((type_id & 0x7fff if type_id & 0x8000 else type_id,
                            rid & 0x7fff if rid & 0x8000 else rid,
                            off << self.shift, ln << self.shift))
                p += 12
        return out

    def blob(self, off, ln, base_candidates=(0,)):
        for base in base_candidates:
            yield self.d[base + off:base + off + ln]


def read_sz(d, p):
    """NUL終端文字列を読む。(text, next_p)"""
    end = d.index(b'\x00', p)
    return dec(d[p:end]), end + 1


def read_name_or_ord(d, p):
    """0xFFFF+u16 の序数形式か、sz か、空(0x00)かを読む。"""
    (w,) = struct.unpack_from('<H', d, p)
    if w == 0xffff:
        (o,) = struct.unpack_from('<H', d, p + 2)
        return f'#{o}', p + 4
    if w == 0x0000:
        return '', p + 1
    return read_sz(d, p)


CLASS_NAMES = {0x80: 'Button', 0x81: 'Edit', 0x82: 'Static', 0x83: 'ListBox',
               0x84: 'ScrollBar', 0x85: 'ComboBox'}


def parse_dialog(d, off, ln):
    """Win3.1 16bit ダイアログテンプレートをパースする。"""
    p = off
    end = off + ln
    (style,) = struct.unpack_from('<I', d, p)
    p += 4
    cdit = d[p]
    p += 1
    x, y, cx, cy = struct.unpack_from('<hhhh', d, p)
    p += 8
    _menu, p = read_name_or_ord(d, p)
    _cls, p = read_name_or_ord(d, p)
    caption, p = read_sz(d, p)
    font = ''
    if style & 0x40:  # DS_SETFONT
        (pt,) = struct.unpack_from('<H', d, p)
        p += 2
        face, p = read_sz(d, p)
        font = f'{pt}pt {face}'
    items = []
    for _ in range(cdit):
        if p + 15 > end:
            break
        ix, iy, icx, icy, iid = struct.unpack_from('<hhhhH', d, p)
        p += 10
        # 本家独自形式: アイテムごとに DWORD スタイルが付く
        (istyle,) = struct.unpack_from('<I', d, p)
        p += 4
        # class: 1バイトの定義済みクラス序数 (0x80-0x85) か、sz のクラス名
        cb = d[p]
        if 0x80 <= cb <= 0x85:
            cls = CLASS_NAMES.get(cb, f'#{cb}')
            p += 1
        else:
            cls, p = read_sz(d, p)
        # text: sz、または 0xFFFF+序数
        (w,) = struct.unpack_from('<H', d, p)
        if w == 0xffff:
            (o,) = struct.unpack_from('<H', d, p + 2)
            text = f'#{o}'
            p += 4
        else:
            text, p = read_sz(d, p)
        extra = d[p]
        p += 1 + extra
        items.append((iid, cls, text))
    return caption, font, items


def parse_menu(d, off, ln):
    p = off
    _ver, hdr = struct.unpack_from('<HH', d, p)
    p += 2 + hdr
    texts = []

    def items(p, depth):
        while p < off + ln:
            (flags,) = struct.unpack_from('<H', d, p)
            p += 2
            is_popup = bool(flags & 0x10)
            if not is_popup:
                p += 2  # id
            t, p = read_sz(d, p)
            texts.append('  ' * depth + t)
            if is_popup:
                p = items(p, depth + 1)
            if flags & 0x80:  # MF_END
                return p
        return p

    items(p, 0)
    return texts


def parse_string_block(d, off, ln, block_id):
    p = off
    out = []
    for i in range(16):
        if p >= off + ln:
            break
        n = d[p]
        p += 1
        if n:
            out.append((((block_id - 1) << 4) + i, dec(d[p:p + n])))
        p += n
    return out


def main():
    for path in TARGETS:
        data = open(path, 'rb').read()
        name = os.path.basename(path)
        try:
            r = Res(data)
            # リソース表の妥当性チェック（表を持たないDLLでは resident names と
            # オフセットが一致し、shift に無効な値が読める）
            (first_type,) = struct.unpack_from('<H', data, r.rsrc + 2)
            if r.shift > 12 or not (first_type == 0 or (first_type & 0x8000 and 1 <= (first_type & 0x7fff) <= 16)):
                print(f'===== {name}: リソース表なし（コード/データ専用モジュール）')
                continue
            ents = r.entries()
        except Exception as e:
            print(f'===== {name}: リソース解析不可 ({e})')
            continue
        dlgs = [e for e in ents if e[0] == RT_DIALOG]
        menus = [e for e in ents if e[0] == RT_MENU]
        strs = [e for e in ents if e[0] == RT_STRING]
        print(f'===== {name}: dialog={len(dlgs)} menu={len(menus)} stringblock={len(strs)}')
        # オフセットの基準（ファイル先頭 or NEヘッダ）をダイアログで検証して決める
        base = 0
        if dlgs:
            ok = False
            for cand in (0, r.lfanew):
                try:
                    cap, _f, items = parse_dialog(data, dlgs[0][2] + cand, dlgs[0][3])
                    if cap and all(0x20 <= ord(c) or ord(c) > 0x7f for c in cap):
                        base = cand
                        ok = True
                        break
                except Exception:
                    pass
            if not ok:
                print('  （ダイアログのオフセット基準を特定できず）')
        for (_t, rid, off, ln) in dlgs:
            try:
                cap, font, items = parse_dialog(data, off + base, ln)
            except Exception as e:
                print(f'  [DLG {rid}] パース失敗: {e}')
                continue
            print(f'  [DLG {rid}] キャプション: {cap!r}' + (f' （{font}）' if font else ''))
            for (iid, cls, text) in items:
                if text:
                    print(f'      - ({cls} id={iid}) {text}')
        for (_t, rid, off, ln) in menus:
            try:
                texts = parse_menu(data, off + base, ln)
            except Exception as e:
                print(f'  [MENU {rid}] パース失敗: {e}')
                continue
            print(f'  [MENU {rid}]')
            for t in texts:
                print(f'      | {t}')
        for (_t, rid, off, ln) in strs:
            for sid, s in parse_string_block(data, off + base, ln, rid):
                print(f'  [STR {sid}] {s}')


if __name__ == '__main__':
    main()
