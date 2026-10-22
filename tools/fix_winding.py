#!/usr/bin/env python3
"""Rende l'orientamento di ogni triangolo coerente con le sue normali.

Con materiali a doppia faccia, un triangolo con l'ordine dei vertici invertito
viene illuminato come se fosse visto da dietro (schegge chiare sulla vernice).
Non sposta vertici: scambia solo due indici dei triangoli invertiti.

  python3 tools/fix_winding.py originale.glb corretto.glb
"""
import json
import struct
import sys

_FMT = {5125: ('I', 4), 5123: ('H', 2), 5121: ('B', 1)}


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def fix_winding(src, dst):
    """Scrive in [dst] il modello corretto; restituisce (girati, totale)."""
    data = bytearray(open(src, 'rb').read())
    json_len = struct.unpack_from('<I', data, 12)[0]
    g = json.loads(data[20:20 + json_len])
    bin_start = 20 + json_len + 8

    def floats(acc_index):
        a = g['accessors'][acc_index]
        v = g['bufferViews'][a['bufferView']]
        if a['componentType'] != 5126:
            return None  # dati quantizzati: li lasciamo come sono
        stride = v.get('byteStride', 12)
        base = bin_start + v.get('byteOffset', 0) + a.get('byteOffset', 0)
        return [struct.unpack_from('<fff', data, base + i * stride) for i in range(a['count'])]

    flipped = total = 0
    seen = set()
    for mesh in g['meshes']:
        for p in mesh['primitives']:
            if 'indices' not in p or 'NORMAL' not in p['attributes'] or p['indices'] in seen:
                continue
            seen.add(p['indices'])
            pos = floats(p['attributes']['POSITION'])
            nor = floats(p['attributes']['NORMAL'])
            if pos is None or nor is None:
                continue
            a = g['accessors'][p['indices']]
            v = g['bufferViews'][a['bufferView']]
            fmt, size = _FMT[a['componentType']]
            base = bin_start + v.get('byteOffset', 0) + a.get('byteOffset', 0)
            for t in range(a['count'] // 3):
                off = base + t * 3 * size
                i0, i1, i2 = struct.unpack_from('<' + fmt * 3, data, off)
                face = _cross(_sub(pos[i1], pos[i0]), _sub(pos[i2], pos[i0]))
                normal = tuple(nor[i0][k] + nor[i1][k] + nor[i2][k] for k in range(3))
                total += 1
                if _dot(face, normal) < 0:
                    struct.pack_into('<' + fmt * 3, data, off, i0, i2, i1)
                    flipped += 1
    with open(dst, 'wb') as f:
        f.write(data)
    return flipped, total


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    flipped, total = fix_winding(sys.argv[1], sys.argv[2])
    print(f'triangoli girati: {flipped} su {total} ({flipped / max(total, 1):.0%})')


if __name__ == '__main__':
    main()
