#!/usr/bin/env python3
"""Batch-decode all figure files in HONDA_EPC.ISO -> PNG + hotspot DB."""
import io, os, re, sqlite3, struct, sys
import pycdlib
from PIL import Image

ISO = '/home/hatch/workspace/epc-project/cd/HONDA_EPC.ISO'
OUT = '/home/hatch/workspace/epc-project/figures'
DB  = '/home/hatch/workspace/epc-project/epc_index.sqlite'
LOG = open('/home/hatch/workspace/epc-project/batch_decode.log', 'w')

def log(*a):
    print(*a); print(*a, file=LOG); LOG.flush()

def make_tiff(stream, w, h):
    # minimal little-endian TIFF, single strip, CCITT G4
    entries = []
    def e(tag, typ, cnt, val): entries.append((tag, typ, cnt, val))
    e(256, 4, 1, w)          # ImageWidth
    e(257, 4, 1, h)          # ImageLength
    e(258, 3, 1, 1)          # BitsPerSample
    e(259, 3, 1, 4)          # Compression = G4
    e(262, 3, 1, 0)          # Photometric = WhiteIsZero
    e(266, 3, 1, 1)          # FillOrder
    e(273, 4, 1, 0)          # StripOffsets (patch later)
    e(277, 3, 1, 1)          # SamplesPerPixel
    e(278, 4, 1, h)          # RowsPerStrip
    e(279, 4, 1, len(stream))# StripByteCounts
    e(292, 4, 1, 0)          # T6Options
    entries.sort()
    n = len(entries)
    hdr = struct.pack('<2sHI', b'II', 42, 8)
    ifd_size = 2 + n*12 + 4
    strip_off = 8 + ifd_size
    ifd = struct.pack('<H', n)
    for tag, typ, cnt, val in entries:
        if tag == 273: val = strip_off
        if typ == 3 and cnt == 1:
            ifd += struct.pack('<HHIHH', tag, typ, cnt, val, 0)
        else:
            ifd += struct.pack('<HHII', tag, typ, cnt, val)
    ifd += struct.pack('<I', 0)
    return hdr + ifd + stream

def segments(data):
    off = 0
    while off + 4 <= len(data):
        if data[off] != 0: break
        ln = struct.unpack('>H', data[off+1:off+3])[0]
        if ln < 4 or off + ln > len(data): break
        yield off, ln, chr(data[off+3])
        off += ln
    return

def main():
    os.makedirs(OUT, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute('DROP TABLE IF EXISTS figures')
    con.execute('DROP TABLE IF EXISTS hotspots')
    con.execute('CREATE TABLE figures (catalog TEXT, subdir TEXT, filename TEXT, width INT, height INT, png TEXT, hotspots INT)')
    con.execute('CREATE TABLE hotspots (catalog TEXT, subdir TEXT, filename TEXT, item TEXT, x1 INT, y1 INT, x2 INT, y2 INT)')
    iso = pycdlib.PyCdlib(); iso.open(ISO)
    n_ok = n_fail = n_skip = 0
    for dirpath, dirnames, filenames in iso.walk(iso_path='/'):
        parts = [p for p in dirpath.split('/') if p]
        if parts and parts[0].upper().startswith('PROGRAM'): continue
        if len(parts) > 2: continue
        catalog = parts[0] if parts else ''
        subdir = parts[1] if len(parts) > 1 else ''
        if not catalog or not catalog[0].isdigit(): continue
        for fn in filenames:
            name = fn.split(';')[0]
            ip = dirpath.rstrip('/') + '/' + fn
            buf = io.BytesIO()
            try: iso.get_file_from_iso_fp(buf, iso_path=ip)
            except Exception as ex: log('READFAIL', ip, ex); continue
            data = buf.getvalue()
            if len(data) < 21 or data[3:4] != b'3'[0:1] and data[3] != 0x33: 
                n_skip += 1; continue
            if data[4:11] != b'       ':
                n_skip += 1; continue
            w = struct.unpack('>H', data[11:13])[0]
            h = struct.unpack('>H', data[13:15])[0]
            seg3len = struct.unpack('>H', data[1:3])[0]
            if not (100 <= w <= 4000 and 100 <= h <= 4000 and 25 <= seg3len <= len(data)):
                n_skip += 1; continue
            stream = data[21:seg3len]
            spots = []
            for off, ln, typ in segments(data):
                if typ == 'C':
                    body = data[off+4:off+ln]
                    for i in range(0, len(body) - 10, 11):
                        x1,y1,x2,y2 = struct.unpack('>HHHH', body[i:i+8])
                        item = body[i+8:i+11].decode('ascii', 'replace').strip()
                        spots.append((item, x1, y1, x2, y2))
            rel = f"{catalog}/{subdir}/{name}.png" if subdir else f"{catalog}/{name}.png"
            outpath = os.path.join(OUT, rel)
            os.makedirs(os.path.dirname(outpath), exist_ok=True)
            try:
                im = Image.open(io.BytesIO(make_tiff(stream, w, h)))
                im.load()
                im.save(outpath, optimize=True)
            except Exception as ex:
                n_fail += 1; log('DECODEFAIL', ip, w, h, repr(ex)[:100]); continue
            con.execute('INSERT INTO figures VALUES (?,?,?,?,?,?,?)', (catalog, subdir, name, w, h, rel, len(spots)))
            for item, x1, y1, x2, y2 in spots:
                con.execute('INSERT INTO hotspots VALUES (?,?,?,?,?,?,?,?)', (catalog, subdir, name, item, x1, y1, x2, y2))
            n_ok += 1
            if n_ok % 500 == 0:
                log('progress ok=', n_ok); con.commit()
    con.commit(); iso.close()
    log(f'DONE ok={n_ok} fail={n_fail} skip={n_skip}')
    cur = con.execute('SELECT COUNT(*), SUM(hotspots) FROM figures')
    log('figures table:', cur.fetchone())
    con.close()

if __name__ == '__main__':
    main()
