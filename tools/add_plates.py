#!/usr/bin/env python3
"""Aggiunge al modello delle targhe su cui l'app disegna il numero.

Ogni targa è un rettangolo 52 x 11 cm con UV 0..1 (materiale `plate`) e una
cornice nera appena dietro. Nel catalogo il modello va poi indicato con
"plateMaterial": "plate".

  python3 tools/add_plates.py in.glb out.glb \\
      --plate 0,0.385,2.0:0,-0.1,1 --plate 0,0.73,-1.94:0,-0.28,-0.96

Ogni --plate è "centro:normale" in coordinate del modello (metri). Centro e
normale si ricavano con `tools/glb_tool.py ray` sulla zona della targa; il
centro va staccato di qualche millimetro dalla superficie.
"""

import argparse
import json
import math
import struct

WIDTH, HEIGHT = 0.52, 0.11
FRAME = 0.015


def normalize(v):
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / length for c in v)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def quad(center, normal, half_w, half_h, offset):
    """Vertici, normali e UV di un rettangolo; u cresce verso la destra di
    chi guarda la targa, v verso il basso (convenzione glTF)."""
    n = normalize(normal)
    up = normalize(tuple(u - n[1] * c for u, c in zip((0, 1, 0), n)))  # Y proiettato
    right = cross(up, n)
    c = tuple(center[k] + n[k] * offset for k in range(3))
    corners = [(-1, 1), (1, 1), (1, -1), (-1, -1)]
    positions = [tuple(c[k] + right[k] * sx * half_w + up[k] * sy * half_h for k in range(3))
                 for sx, sy in corners]
    uvs = [((sx + 1) / 2, (1 - sy) / 2) for sx, sy in corners]
    # Antiorari visti dal lato della normale: right x up = n.
    return positions, [n] * 4, uvs, [0, 2, 1, 0, 3, 2]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--plate', action='append', required=True, help='cx,cy,cz:nx,ny,nz')
    args = parser.parse_args()

    with open(args.input, 'rb') as f:
        data = f.read()
    json_length = struct.unpack_from('<I', data, 12)[0]
    gltf = json.loads(data[20:20 + json_length])
    bin_offset = 20 + json_length
    bin_length = struct.unpack_from('<I', data, bin_offset)[0]
    binary = bytearray(data[bin_offset + 8:bin_offset + 8 + bin_length])

    materials = gltf.setdefault('materials', [])
    names = [m.get('name') for m in materials]
    if 'plate' not in names:
        materials.append({'name': 'plate', 'pbrMetallicRoughness': {
            'baseColorFactor': [0.95, 0.95, 0.93, 1], 'metallicFactor': 0, 'roughnessFactor': 0.5}})
    if 'plate_frame' not in names:
        materials.append({'name': 'plate_frame', 'pbrMetallicRoughness': {
            'baseColorFactor': [0.03, 0.03, 0.035, 1], 'metallicFactor': 0, 'roughnessFactor': 0.7}})
    names = [m.get('name') for m in materials]

    def add_accessor(values, component, kind, target):
        while len(binary) % 4:
            binary.append(0)
        if component == 5125:
            payload = struct.pack(f'<{len(values)}I', *values)
        else:
            flat = [c for v in values for c in v]
            payload = struct.pack(f'<{len(flat)}f', *flat)
        gltf.setdefault('bufferViews', []).append(
            {'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(payload), 'target': target})
        binary.extend(payload)
        accessor = {'bufferView': len(gltf['bufferViews']) - 1, 'componentType': component,
                    'count': len(values), 'type': kind}
        if kind == 'VEC3' and target == 34962 and values and len(values[0]) == 3:
            accessor['min'] = [min(v[k] for v in values) for k in range(3)]
            accessor['max'] = [max(v[k] for v in values) for k in range(3)]
        gltf.setdefault('accessors', []).append(accessor)
        return len(gltf['accessors']) - 1

    primitives = []
    for spec in args.plate:
        center_text, normal_text = spec.split(':')
        center = tuple(float(v) for v in center_text.split(','))
        normal = tuple(float(v) for v in normal_text.split(','))
        for half_w, half_h, offset, material in (
                (WIDTH / 2 + FRAME, HEIGHT / 2 + FRAME, 0.0, 'plate_frame'),
                (WIDTH / 2, HEIGHT / 2, 0.004, 'plate')):
            positions, normals, uvs, indices = quad(center, normal, half_w, half_h, offset)
            primitives.append({
                'attributes': {
                    'POSITION': add_accessor(positions, 5126, 'VEC3', 34962),
                    'NORMAL': add_accessor(normals, 5126, 'VEC3', 34962),
                    'TEXCOORD_0': add_accessor(uvs, 5126, 'VEC2', 34962),
                },
                'indices': add_accessor(indices, 5125, 'SCALAR', 34963),
                'material': names.index(material),
            })

    gltf['meshes'].append({'name': 'plates', 'primitives': primitives})
    gltf['nodes'].append({'name': 'plates', 'mesh': len(gltf['meshes']) - 1})
    gltf['scenes'][gltf.get('scene', 0)]['nodes'].append(len(gltf['nodes']) - 1)

    while len(binary) % 4:
        binary.append(0)
    gltf['buffers'][0]['byteLength'] = len(binary)
    chunk = json.dumps(gltf, separators=(',', ':')).encode()
    chunk += b' ' * ((4 - len(chunk) % 4) % 4)
    total = 12 + 8 + len(chunk) + 8 + len(binary)
    with open(args.output, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(chunk), 0x4E4F534A))
        f.write(chunk)
        f.write(struct.pack('<II', len(binary), 0x004E4942))
        f.write(binary)
    print(f'{len(args.plate)} targhe aggiunte -> {args.output}')


if __name__ == '__main__':
    main()
