#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A班（ルート .CD ファイル群）の全件解析・検証スクリプト。

対象: REUSE.CD / HAMP.CD / CDJHTBL.CD / GRPBRTBL.CD / HPLTBLJH.CD /
      KRHHDKI.CD / KRHHKI.CD / TSMIR.CD / IMTBL.CD
突合相手: KSRBHMH.CD（モデルマスタ）, epc_index.sqlite (parts2)

使い方: python3 analysis/a_root_verify.py
各ファイルについて「全件パースできること」「ファイル末尾と一致すること」
「KSRBHMH ブロックとの突合」を検証し、結果を表示する。
"""
import re
import sqlite3
import struct
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
EXT = BASE / "cd" / "extracted"


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


# ------------------------------------------------------------ KSRBHMH
def load_ksrbhmh():
    """KSRBHMH.CD をレコードチェーンで読み、レコード一覧を返す。"""
    data = (EXT / "KSRBHMH.CD").read_bytes()
    offs, off = [], 0
    while off < len(data):
        ln = u16(data, off)
        offs.append((off, ln))
        off += ln
    assert off == len(data), "KSRBHMH chain does not reach EOF"
    return data, offs


def field(data, o, a, b):
    return data[o + a:o + b].decode("cp932", errors="replace").strip()


def contiguous_blocks(data, offs, keyfunc):
    """keyfunc(rec_offset) -> key の連続ブロック [(key, start, total_len)]"""
    blocks = []
    cur = None
    for (o, ln) in offs:
        k = keyfunc(o)
        if cur and cur[0] == k and cur[1] + cur[2] == o:
            cur[2] += ln
        else:
            cur = [k, o, ln]
            blocks.append(cur)
    return blocks


# ------------------------------------------------------------ KRHHDKI
def verify_krhhdki(data, offs):
    kd = (EXT / "KRHHDKI.CD").read_bytes()
    # 型式コード (bytes 37..44) の連続ブロック表
    blocks = defaultdict(list)
    for k, s, ln in contiguous_blocks(data, offs, lambda o: field(data, o, 37, 44)):
        blocks[k].append((s, ln))
    recs, off = [], 0
    while off < len(kd):
        ln = u16(kd, off)
        recs.append(kd[off:off + ln])
        off += ln
    assert off == len(kd), "KRHHDKI chain does not reach EOF"
    ok = 0
    for r in recs:
        tc = r[2:13].decode("ascii").strip()
        pairs = [struct.unpack_from("<II", r, 13 + 8 * i)
                 for i in range((len(r) - 13) // 8)]
        assert pairs == blocks[tc], f"KRHHDKI mismatch: {tc}"
        ok += 1
    print(f"KRHHDKI.CD: {len(recs)} records, all (offset,length) pairs match "
          f"KSRBHMH type-code blocks ({ok}/{len(recs)})")
    return recs


# ------------------------------------------------------------ KRHHKI
def verify_krhhki(data, offs):
    kd = (EXT / "KRHHKI.CD").read_bytes()
    assert len(kd) == 26 * 501
    blocks = {(k, s): ln for k, s, ln in
              contiguous_blocks(data, offs, lambda o: field(data, o, 28, 36))}
    ok = 0
    for i in range(1, 501):  # record 0 はヘッダ/ダミー
        r = kd[i * 26:(i + 1) * 26]
        tf = r[0:13].decode("ascii").strip()
        cls = r[13:18].decode("ascii").strip()
        a, b = struct.unpack_from("<II", r, 18)
        # 類別番号は数字 4 桁 (旧型式) または 5 桁 (新型式)
        assert cls.isdigit() and len(cls) in (4, 5)
        assert blocks[(tf, a)] == b, f"KRHHKI mismatch: {tf}"
        # 類別番号はブロック先頭レコードの code1 フィールド [2:7] と一致する
        code1 = data[a + 2:a + 7].decode("ascii", errors="replace").strip()
        assert code1 == cls, f"KRHHKI class != code1: {tf}"
        ok += 1
    print(f"KRHHKI.CD: 26B x 501 (header 1 + entries {ok}), all entries match "
          f"KSRBHMH type-full blocks")
    return ok


# ------------------------------------------------------------ TSMIR
def verify_tsmir(data, offs):
    ts = (EXT / "TSMIR.CD").read_bytes()
    # (型式フル, 車名) の連続ラン表
    runs = defaultdict(list)
    for (tf, nm), s, ln in contiguous_blocks(
            data, offs, lambda o: (field(data, o, 28, 36), field(data, o, 13, 27))):
        runs[(tf, nm)].append((s, ln))
    recs, off = [], 0
    while off < len(ts):
        ln = u16(ts, off)
        recs.append(ts[off:off + ln])
        off += ln
    assert off == len(ts), "TSMIR chain does not reach EOF"
    npair = 0
    for r in recs:
        name = r[2:17].decode("ascii").strip()
        body = r[17:]
        assert len(body) % 21 == 0
        for i in range(len(body) // 21):
            e = body[i * 21:(i + 1) * 21]
            tf = e[0:13].decode("ascii").strip()
            a, b = struct.unpack_from("<II", e, 13)
            # KSRBHMH の車名フィールドは 14 文字で切れるため name[:14] で照合
            assert (a, b) in runs[(tf, name[:14])], f"TSMIR mismatch: {name} {tf}"
            npair += 1
    print(f"TSMIR.CD: {len(recs)} records / {npair} entries, all match "
          f"KSRBHMH (type-full, car-name) runs")
    return recs


# ------------------------------------------------------------ IMTBL
def verify_imtbl():
    data = (EXT / "IMTBL.CD").read_bytes()
    assert len(data) % 66 == 0
    recs = [data[i * 66:(i + 1) * 66] for i in range(len(data) // 66)]
    keys = set()
    for r in recs:
        code = r[0:10].decode("ascii", errors="replace").strip()
        sub = r[10:16].decode("ascii", errors="replace").strip()
        assert code, "empty color code"
        keys.add((code, sub))
    assert len(keys) == len(recs), "(code, sub) not unique"
    print(f"IMTBL.CD: 66B x {len(recs)} records, (color-code, sub) unique")
    return recs


# ------------------------------------------------------------ GRPBRTBL
def verify_grpbrtbl():
    data = (EXT / "GRPBRTBL.CD").read_bytes()
    assert len(data) == 44 * 9
    rows = []
    for i in range(9):
        r = data[i * 44:(i + 1) * 44]
        rows.append((r[0:2].decode("ascii").strip(),
                     r[2:41].decode("cp932").strip(),
                     r[41:44].decode("ascii").strip()))
    print(f"GRPBRTBL.CD: 44B x 9 records: {rows}")
    return rows


# ------------------------------------------------------------ REUSE / HAMP
def verify_text_table(fn, linelen):
    raw = (EXT / fn).read_bytes()
    text = raw.decode("cp932")
    lines = text.split("\r\n")
    assert lines[-1] == "" and all(len(l) == linelen for l in lines[:-1])
    lines = lines[:-1]
    assert len(raw) == len(lines) * (linelen + 2)
    pat_a = re.compile(r"^[0-9A-Z]{5}[0-9A-Z]{3}[0-9A-Z]{3}$")
    n_a = sum(1 for l in lines if pat_a.match(l[0:11]))
    n_price = sum(1 for l in lines if l[27:34].strip().isdigit())
    n_open = sum(1 for l in lines if "ｵｰﾌﾟﾝ" in l[27:34])
    print(f"{fn}: {linelen} chars x {len(lines)} lines (+CRLF), "
          f"A-field partno-like {n_a}, price numeric {n_price}, open-price {n_open}, "
          f"col26 '4': {sum(1 for l in lines if l[26] == '4')}")
    return lines


def price_crosscheck(lines, label):
    con = sqlite3.connect(BASE / "epc_index.sqlite")
    prices = {}
    for pno, pr in con.execute(
            "SELECT partno, price FROM parts2 WHERE price IS NOT NULL"):
        prices.setdefault(pno[:11], set()).add(pr)
    same = diff = none = 0
    for l in lines:
        pr = l[27:34].strip()
        if not pr.isdigit():
            continue
        s = prices.get(l[0:11])
        if s is None:
            none += 1
        elif int(pr) in s:
            same += 1
        else:
            diff += 1
    print(f"  {label} price vs DISC1 PLMST: same {same} / differs {diff} / "
          f"not in DISC1 {none}")


# ------------------------------------------------------------ HPLTBLJH
def verify_hpltbljh():
    """ルート .CD ファイルの実サイズと HPLTBLJH.CD のサイズ列を突合する。

    並びは HMEPCFIL.DLl 内のファイル名リスト順。
    サイズは u16LE 低位ワードで記録され、65536 以上の場合は続けて
    u16LE 高位ワードが置かれる。
    """
    order = ["TSMIR.CD", "KRHHKI.CD", "KRHHDKI.CD", "KSRBHMH.CD",
             "SYSBMST.CD", "GRPBRTBL.CD", "IMTBL.CD", "CDJHTBL.CD"]
    data = (EXT / "HPLTBLJH.CD").read_bytes()
    vals = [u16(data, i) for i in range(0, len(data), 2)]
    pos = 0
    for fn in order:
        size = (EXT / fn).stat().st_size
        low = vals[pos]
        pos += 1
        if low != size:
            high = vals[pos]
            pos += 1
            assert low + high * 65536 == size, f"HPLTBLJH mismatch: {fn}"
    assert pos == len(vals), "HPLTBLJH has trailing values"
    print(f"HPLTBLJH.CD: size list matches all {len(order)} root files "
          f"({len(vals)} u16 values)")


# ------------------------------------------------------------ CDJHTBL
def verify_cdjtbl():
    data = (EXT / "CDJHTBL.CD").read_bytes().decode("ascii")
    assert re.fullmatch(r"1\d{8}\d{8}", data)
    print(f"CDJHTBL.CD: 17 chars: disc='{data[0]}', "
          f"date1={data[1:5]}-{data[5:7]}-{data[7:9]}, "
          f"date2={data[9:13]}-{data[13:15]}-{data[15:17]}")


def main():
    data, offs = load_ksrbhmh()
    print(f"KSRBHMH.CD: {len(offs)} records (cross-check target)")
    verify_krhhdki(data, offs)
    verify_krhhki(data, offs)
    verify_tsmir(data, offs)
    verify_imtbl()
    verify_grpbrtbl()
    reuse = verify_text_table("REUSE.CD", 84)
    hamp = verify_text_table("HAMP.CD", 90)
    price_crosscheck(reuse, "REUSE")
    price_crosscheck(hamp, "HAMP")
    verify_hpltbljh()
    verify_cdjtbl()
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
