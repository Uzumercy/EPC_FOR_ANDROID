#!/usr/bin/env python3
"""Verify M-folder (front matter) figure files across all 82 catalogs.

For every file in each catalog's M/ directory on the ISO:
- parse the segment chain, record segment type pattern
- decode the image segment ('3' or '2') with the existing method
  (stream from segment offset+21, w/h u16BE at +11/+13, TIFF wrapper + PIL)
- count hotspots in 'C' segments
Also census segment patterns in the numeric subdirs for comparison.
"""
import io
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.expanduser('~/workspace/epc-project/converter'))
from epcconv.parsers import figure_segments, make_tiff, parse_hotspots  # noqa: E402
import pycdlib  # noqa: E402
from PIL import Image  # noqa: E402

ISO = os.path.expanduser('~/workspace/epc-project/cd/HONDA_EPC.ISO')
SAMPLE_DIR = os.path.expanduser('~/workspace/epc-project/analysis/work/m_samples')
os.makedirs(SAMPLE_DIR, exist_ok=True)

iso = pycdlib.PyCdlib()
iso.open(ISO)
catalogs = []
for dirname, dirlist, filelist in iso.walk(iso_path='/'):
    if dirname == '/':
        catalogs = sorted(d for d in dirlist if d != 'PROGRAM')
        break


def get(path):
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=path)
    return buf.getvalue()


def decode_image(data):
    """Return (ok, w, h, segtype) using the standard figure decode."""
    for off, ln, t in figure_segments(data):
        if t in ('2', '3'):
            w, h = struct.unpack_from('>HH', data, off + 11)
            stream = data[off + 21:off + ln]
            img = Image.open(io.BytesIO(make_tiff(stream, w, h)))
            img.load()
            return True, w, h, t
    return False, 0, 0, None


stats = Counter()
failures = []
samples_saved = 0
for cat in catalogs:
    # M dir
    mfiles = []
    for dirname, dirlist, filelist in iso.walk(iso_path=f'/{cat}/M'):
        mfiles = filelist
    for f in sorted(mfiles):
        data = get(f'/{cat}/M/{f}')
        stats['m_files'] += 1
        types = ''.join(t for _, _, t in figure_segments(data))
        stats[f'm_pattern_{types}'] += 1
        spots = parse_hotspots(data)
        stats['m_hotspots_total'] += len(spots)
        if len(spots):
            stats['m_files_with_hotspots'] += 1
        try:
            ok, w, h, t = decode_image(data)
        except Exception as e:
            ok, w, h, t = False, 0, 0, None
            failures.append((cat, f, str(e)[:80]))
        if ok:
            stats['m_decode_ok'] += 1
            stats[f'm_segtype_{t}'] += 1
            if samples_saved < 6 and (f.endswith('.1') and '7100' in f or '7200' in f or '0300' in f):
                for off, ln, tt in figure_segments(data):
                    if tt in ('2', '3'):
                        ww, hh = struct.unpack_from('>HH', data, off + 11)
                        img = Image.open(io.BytesIO(
                            make_tiff(data[off + 21:off + ln], ww, hh)))
                        img.load()
                        img.save(os.path.join(SAMPLE_DIR, f'{cat}_{f}.png'))
                        samples_saved += 1
                        break
        else:
            stats['m_decode_fail'] += 1
            if len(failures) < 20 and not any(x[1] == f and x[0] == cat for x in failures):
                failures.append((cat, f, 'no image segment or decode error'))
    # numeric subdirs: segment pattern census (sample: all files)
    subs = []
    for dirname, dirlist, filelist in iso.walk(iso_path=f'/{cat}'):
        if dirname == f'/{cat}':
            subs = [d for d in dirlist if d != 'M']
            break
    for s in subs:
        for dirname, dirlist, filelist in iso.walk(iso_path=f'/{cat}/{s}'):
            for f in filelist:
                data = get(f'/{cat}/{s}/{f}')
                types = ''.join(t for _, _, t in figure_segments(data))
                stats[f'num_pattern_{types}'] += 1
                stats['num_files'] += 1

print(dict(stats))
print('failures:', failures[:20])
iso.close()
