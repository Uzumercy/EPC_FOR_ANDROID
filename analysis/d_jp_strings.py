#!/usr/bin/env python3
"""D班: NEバイナリから cp932 日本語文字列を抽出する。

ダイアログリソースや文字列テーブルに埋まっている日本語テキストを拾う。
使い方: d_jp_strings.py <file...> [--min N]
各文字列を「ファイル @オフセット: テキスト」で出す。
"""
import sys

FILES = [a for a in sys.argv[1:] if not a.startswith('--')]
MIN = 3


def is_lead(b):
    return (0x81 <= b <= 0x9f) or (0xe0 <= b <= 0xfc)


def is_trail(b):
    return (0x40 <= b <= 0x7e) or (0x80 <= b <= 0xfc)


def extract(data):
    out = []
    i = 0
    n = len(data)
    while i < n:
        start = i
        chars = []
        jp = 0
        while i < n:
            b = data[i]
            if 0x20 <= b <= 0x7e:
                chars.append(chr(b))
                i += 1
            elif is_lead(b) and i + 1 < n and is_trail(data[i + 1]):
                try:
                    ch = data[i:i + 2].decode('cp932')
                except Exception:
                    break
                chars.append(ch)
                jp += 1
                i += 2
            elif 0xa1 <= b <= 0xdf:  # 半角カナ
                try:
                    ch = bytes([b]).decode('cp932')
                except Exception:
                    break
                chars.append(ch)
                jp += 1
                i += 1
            else:
                break
        s = ''.join(chars)
        if jp >= 1 and len(s) >= MIN and any(ord(c) > 0x7f for c in s):
            out.append((start, s))
        i = max(i, start + 1)
    return out


for path in FILES:
    data = open(path, 'rb').read()
    print(f'===== {path}')
    for off, s in extract(data):
        print(f'@{off:#08x}: {s}')
