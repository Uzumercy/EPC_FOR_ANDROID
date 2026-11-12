"""Record parsers for the Honda EPC CD data files.

Every parser here is a faithful port of the analysis scripts that
produced the project's reference database (epc_index.sqlite), with the
known fixes baked in from the start:

* PLMST.CD is parsed with a plain u16LE length-chain walk that must land
  exactly on EOF — the original ad-hoc parser silently stopped at the
  first over-long record in 14 catalogs (see repair_plmst.py).
* All text is decoded as cp932.  Python's 'shift_jis' codec maps
  halfwidth katakana bytes (0xA1-0xDF) to U+FFFD and garbles grade
  names (see rebuild_models.py).
* PLMST applicability tails are parsed with the confirmed grammar whose
  group chain starts at offset ``7 + tail[7]`` (see prep_v4.py).

See EPC_FORMAT_REPORT.md for the full format documentation.
"""
import re
import struct
import unicodedata


# ---------------------------------------------------------------- PLMST --
def parse_plmst(data):
    """Parse one PLMST.CD (parts list) file.

    Returns a list of (figkey, partno, name, price, tail) tuples where
    ``tail`` is the raw applicability blob (bytes after the 58-byte text
    block).  Raises ValueError if the length chain does not land exactly
    on EOF — a truncated or misaligned parse must never pass silently.
    """
    recs = []
    off = 0
    while off + 2 <= len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < 20 or off + ln > len(data):
            raise ValueError(f'PLMST chain break at {off} len={ln}')
        rec = data[off:off + ln]
        figkey = rec[2:12].decode('ascii', 'replace')
        partno = rec[12:24].decode('ascii', 'replace').strip().replace(' ', '')
        # The 58-byte text block holds "name <spaces> price" with the
        # price right-aligned at the block end.  The price regex must
        # run on the block BEFORE stripping: the name side is normally
        # blank-padded on the left by one space, and a part with an
        # empty name is just spaces + price (77961SD4N81 in 11SD411 /
        # 11SG001) — stripping first would glue the price to the name
        # side and lose it.  (The legacy repair_plmst.py stripped first;
        # that is why the one 11SD401 copy of that part reads
        # name='27000', price=None in the old reference DB.)
        field = rec[24:82].decode('cp932', 'replace')
        price = None
        name = field.strip()
        m = re.search(r'\s+(\d+)$', field)
        if m:
            price = int(m.group(1))
            name = field[:m.start()].strip()
        recs.append((figkey, partno, name, price, rec[82:]))
        off += ln
    if off != len(data):
        raise ValueError(f'PLMST chain ends at {off} != file size {len(data)}')
    return recs


def parse_figkey(fk):
    """Split a PLMST figkey head into (block, figure, sub, item)."""
    return (fk[0:3].strip(), fk[3:5].strip(), fk[5:7].strip(), fk[7:10].strip())


# ------------------------------------------------------- PLMST tail -----
_QTY_FIELD = re.compile(rb'^([ ]{0,2}\d{1,3}|[ ]{2}N)$')


def parse_chain(tail, start):
    """Parse one applicability group chain starting at ``start``.

    Grammar (confirmed against 609,705 of 609,952 records): a sequence of
    groups; each group is [u16LE total length][4 bytes unused] then either
    a quantity field (3 ASCII bytes, e.g. '  1' or '  N') followed by
    u16LE model-ID codes (type A), or a '(...)' remark string followed by
    the codes (type B).  Returns [(qty_or_None, [codes...]), ...] or
    None if the chain does not consume the tail exactly.
    """
    groups = []
    i = start
    while i < len(tail):
        if i + 9 > len(tail):
            return None
        glen = struct.unpack('<H', tail[i:i + 2])[0]
        if glen < 9 or i + glen > len(tail):
            return None
        f3 = tail[i + 6:i + 9]
        if b')' in f3 or f3[:1] == b'(':
            end = tail.find(b')', i + 6, i + glen)
            if end < 0:
                return None
            cs = end + 1
            if (glen - (cs - i)) % 2:
                return None
            codes = [struct.unpack('<H', tail[j:j + 2])[0]
                     for j in range(cs, i + glen - 1, 2)]
            groups.append((None, codes))
        elif _QTY_FIELD.match(f3):
            qty = int(f3.decode('ascii').strip()) if f3.strip().isdigit() else None
            if (glen - 9) % 2:
                return None
            codes = [struct.unpack('<H', tail[j:j + 2])[0]
                     for j in range(i + 9, i + glen - 1, 2)]
            groups.append((qty, codes))
        else:
            return None
        i += glen
    return groups if i == len(tail) else None


def parse_tail(tail):
    """Parse a PLMST applicability tail.

    The confirmed grammar starts the group chain at ``7 + tail[7]``;
    a few historical offsets are tried as fallbacks, in the same order
    the reference build (prep_v4.py) used.  Returns the group list, or
    None when no candidate parses (247 of 609,952 records on DISC1 —
    those parts simply carry no applicability data).
    """
    if not tail or len(tail) < 11:
        return None
    cands = []
    for s in (7 + tail[7], 9, 11, 13, 15):
        if s not in cands:
            cands.append(s)
    for s in cands:
        g = parse_chain(tail, s)
        if g is not None:
            return g
    return None


# ------------------------------------------------------------ KSRBHMH ---
def parse_ksrbhmh(path):
    """Parse KSRBHMH.CD (model master) -> list of model dicts.

    Text fields are cp932.  The name/type_full boundary normally sits at
    byte 29, but when type_full then starts with '-' the boundary is one
    byte earlier — the rule the original parse applied (9,845 shifted
    records).  The record tail (from byte 105) is a u16LE list: the
    model's applicability band pair first, then SYSBMST record indices
    (equipment).  ``ids`` is derived positionally from each record's own
    tail bytes.
    """
    d = open(path, 'rb').read()
    recs, off = [], 0
    while off + 2 <= len(d):
        ln = struct.unpack('<H', d[off:off + 2])[0]
        if ln < 105 or off + ln > len(d):
            raise ValueError(f'KSRBHMH bad record length {ln} at {off}')
        recs.append(d[off:off + ln])
        off += ln
    if off != len(d):
        raise ValueError(f'KSRBHMH chain consumed {off} of {len(d)}')
    out = []
    for i, rec in enumerate(recs):
        def txt(a, b):
            return rec[a:b].decode('cp932').strip()
        name, type_full = txt(13, 29), txt(29, 37)
        if type_full.startswith('-'):
            name, type_full = txt(13, 28), txt(28, 37)
        tail = rec[105:]
        if len(tail) % 2:
            raise ValueError(f'KSRBHMH odd tail at record {i}')
        ids = [struct.unpack_from('<H', tail, j)[0]
               for j in range(0, len(tail), 2)]
        out.append(dict(
            idx=i, code1=txt(2, 6), code2=txt(6, 13), name=name,
            type_full=type_full, type_code=txt(37, 45),
            serial_from=txt(53, 60), serial_to=txt(61, 68),
            grade=txt(68, 86), trans=txt(86, 89), engine=txt(89, 97),
            catalog=txt(97, 105), tail=tail,
            ids=','.join(str(v) for v in ids)))
    return out


# ------------------------------------------------------------- SYSBMST --
def parse_sysbmst(path):
    """Parse SYSBMST.CD (equipment master) -> [(record_index, name)].

    Fixed 20-byte records: [18-byte cp932 name][u16LE].  Models refer to
    records by their 0-based file position, NOT by the stored u16 value.
    Names are NFKC-normalized for display.
    """
    d = open(path, 'rb').read()
    if len(d) % 20:
        raise ValueError(f'SYSBMST size {len(d)} not a multiple of 20')
    rows = []
    for i in range(len(d) // 20):
        name = unicodedata.normalize(
            'NFKC', d[i * 20:i * 20 + 18].decode('cp932'))
        name = re.sub(r'\s+', ' ', name).strip()
        rows.append((i, name))
    return rows


# ------------------------------------------------- GRPTBL/BLKTBL/TYTBL --
def parse_grp(data):
    """GRPTBL.CD: group table (length-prefixed records)."""
    recs, off = [], 0
    while off + 2 <= len(data):
        ln = struct.unpack('<H', data[off:off + 2])[0]
        if ln < 54 or off + ln > len(data):
            break
        rec = data[off:off + ln]
        recs.append(dict(no=rec[2:4].decode('ascii', 'replace').strip(),
                         name=rec[4:43].decode('cp932', 'replace').strip(),
                         code=rec[43:46].decode('ascii', 'replace').strip(),
                         link=rec[46:54]))
        off += ln
    return recs


def parse_blk(data):
    """BLKTBL.CD: block-range -> group link table (fixed 25-byte records)."""
    recs = []
    for i in range(0, len(data) - 24, 25):
        rec = data[i:i + 25]
        span = rec[0:14].decode('ascii', 'replace')
        toks = re.findall(r'([A-Z]+)\s*(\d+)', span)
        if len(toks) < 2:
            continue
        recs.append(dict(fblock=toks[0][0], fnum=int(toks[0][1]),
                         tblock=toks[1][0], tnum=int(toks[1][1]),
                         link=rec[17:25]))
    return recs


def parse_title(rec):
    """BLKTYTBL title: fixed 50-byte cp932 field at rec[19:69].

    Verified strict for all 82 DISC1 catalogs; the fallback (cut at the
    first run of 4+ spaces) covers any record whose fixed field contains
    control bytes.
    """
    if len(rec) >= 69:
        try:
            t = rec[19:69].decode('cp932')
            if all(ord(c) >= 0x20 for c in t):
                return re.sub(r' +', ' ', t).strip(), 'fixed50'
        except UnicodeDecodeError:
            pass
    txt = rec[19:].decode('cp932', 'replace')
    txt = re.split(r' {4,}', txt)[0]
    return re.sub(r' +', ' ', txt).strip(), 'fallback'


def parse_blkty(data):
    """BLKTYTBL.CD: block/figure title table -> (records, method counts)."""
    recs, off = [], 0
    methods = {'fixed50': 0, 'fallback': 0}
    while off + 2 <= len(data):
        ln = struct.unpack('<H', data[off:off + 2])[0]
        if ln < 20 or off + ln > len(data):
            break
        rec = data[off:off + ln]
        fk = rec[2:9]
        title, how = parse_title(rec)
        methods[how] += 1
        recs.append(dict(block=fk[0:3].decode('ascii', 'replace').strip(),
                         fig=fk[3:5].decode('ascii', 'replace').strip(),
                         sub=fk[5:7].decode('ascii', 'replace').strip(),
                         code=rec[9:19].decode('ascii', 'replace').strip(),
                         title=title))
        off += ln
    return recs, methods


# ------------------------------------------------------------- figures --
def make_tiff(stream, w, h):
    """Wrap a raw CCITT Group 4 stream in a minimal little-endian TIFF
    so Pillow/libtiff can decode it (identical to batch_decode.py)."""
    entries = []

    def e(tag, typ, cnt, val):
        entries.append((tag, typ, cnt, val))
    e(256, 4, 1, w)            # ImageWidth
    e(257, 4, 1, h)            # ImageLength
    e(258, 3, 1, 1)            # BitsPerSample
    e(259, 3, 1, 4)            # Compression = G4
    e(262, 3, 1, 0)            # Photometric = WhiteIsZero
    e(266, 3, 1, 1)            # FillOrder
    e(273, 4, 1, 0)            # StripOffsets (patched below)
    e(277, 3, 1, 1)            # SamplesPerPixel
    e(278, 4, 1, h)            # RowsPerStrip
    e(279, 4, 1, len(stream))  # StripByteCounts
    e(292, 4, 1, 0)            # T6Options
    entries.sort()
    n = len(entries)
    hdr = struct.pack('<2sHI', b'II', 42, 8)
    ifd_size = 2 + n * 12 + 4
    strip_off = 8 + ifd_size
    ifd = struct.pack('<H', n)
    for tag, typ, cnt, val in entries:
        if tag == 273:
            val = strip_off
        if typ == 3 and cnt == 1:
            ifd += struct.pack('<HHIHH', tag, typ, cnt, val, 0)
        else:
            ifd += struct.pack('<HHII', tag, typ, cnt, val)
    ifd += struct.pack('<I', 0)
    return hdr + ifd + stream


def figure_segments(data):
    """Yield (offset, length, type_char) for the segment chain of a
    figure file: [0x00][u16BE total length][type]...  '3' is the image
    segment, 'C' the hotspot table."""
    off = 0
    while off + 4 <= len(data):
        if data[off] != 0:
            break
        ln = struct.unpack('>H', data[off + 1:off + 3])[0]
        if ln < 4 or off + ln > len(data):
            break
        yield off, ln, chr(data[off + 3])
        off += ln
    return


def parse_hotspots(data):
    """Extract hotspot records from a figure file's 'C' segments.

    Each hotspot is an 11-byte record: x1, y1, x2, y2 (u16BE) + a
    3-character item number."""
    spots = []
    for off, ln, typ in figure_segments(data):
        if typ == 'C':
            body = data[off + 4:off + ln]
            for i in range(0, len(body) - 10, 11):
                x1, y1, x2, y2 = struct.unpack('>HHHH', body[i:i + 8])
                item = body[i + 8:i + 11].decode('ascii', 'replace').strip()
                spots.append((item, x1, y1, x2, y2))
    return spots
