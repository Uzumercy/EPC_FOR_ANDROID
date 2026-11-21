#!/usr/bin/env python3
"""B班 探索1: 11SA702 の各ファイルの素性確認"""
import struct, os, collections, re

BASE = os.path.expanduser('~/workspace/epc-project/cd/extracted/11SA702/')

def chain(data):
    off = 0; recs = []
    while off < len(data):
        ln = struct.unpack_from('<H', data, off)[0]
        if ln < 2 or off + ln > len(data):
            return recs, off
        recs.append(data[off:off+ln]); off += ln
    return recs, off

print('=== catalog file sizes (11SA702) ===')
sizes = {}
for f in sorted(os.listdir(BASE)):
    p = os.path.join(BASE, f)
    if os.path.isfile(p):
        sizes[f] = os.path.getsize(p)
        print(f'{f:16s} {sizes[f]:>9d}')

print()
print('=== PLBTBLJH u32LE list vs sizes ===')
d = open(BASE + 'PLBTBLJH.CD', 'rb').read()
u32 = struct.unpack('<%dI' % (len(d)//4), d)
print('u32s:', u32)
sizevals = set(sizes.values())
for v in u32:
    hit = [k for k, s in sizes.items() if s == v]
    print(v, '== size of', hit if hit else '')

print()
print('=== PLCKTBL 20B slots? ===')
d = open(BASE + 'PLCKTBL.CD', 'rb').read()
print('len', len(d), 'len%20 =', len(d) % 20)
for i in range(0, len(d), 20):
    slot = d[i:i+20]
    print(i//20, repr(slot.decode('cp932', errors='replace')))

print()
print('=== PLGKTBL 17B records ===')
d = open(BASE + 'PLGKTBL.CD', 'rb').read()
print('len', len(d), 'len%17 =', len(d) % 17, 'records:', len(d)//17)
blocks = collections.Counter()
serials = {}
for i in range(0, len(d), 17):
    r = d[i:i+17]
    blk = r[:10].decode('ascii', errors='replace').strip()
    ser = r[10:17].decode('ascii', errors='replace')
    blocks[blk] += 1
    serials.setdefault(blk, []).append(ser)
print('blocks:', dict(blocks))
for b, ss in serials.items():
    print(b, 'n=', len(ss), 'first5:', ss[:5], 'last3:', ss[-3:],
          'sorted:', ss == sorted(ss), 'unique:', len(set(ss)))
