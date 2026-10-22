#!/usr/bin/env python3
"""Analizza un modello .glb per compilare la sua voce in catalog.json.

Solo libreria standard. Esempi:

  # Materiali (colore, triangoli) e ingombri dei nodi
  python3 tools/glb_tool.py info models/volkswagen_golf_8.glb

  # Primo punto colpito da un raggio: posizione, normale e materiale.
  # Per un punto sul cofano si spara dall'alto verso il basso (-Y).
  python3 tools/glb_tool.py ray models/volkswagen_golf_8.glb \
      --origin 9.43 10 -20.2 --direction 0 -1 0

I raggi sono lenti (Python puro): qualche secondo ciascuno.
"""

import argparse
import json
import struct

_COMPONENTS = {5126: ('f', 4), 5125: ('I', 4), 5123: ('H', 2), 5122: ('h', 2),
               5121: ('B', 1), 5120: ('b', 1)}
_NORMALIZED_MAX = {5123: 65535, 5122: 32767, 5121: 255, 5120: 127}
_WIDTH = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


class Glb:
    def __init__(self, path):
        with open(path, 'rb') as f:
            self.data = f.read()
        json_length = struct.unpack_from('<I', self.data, 12)[0]
        self.gltf = json.loads(self.data[20:20 + json_length])
        self.bin_start = 20 + json_length + 8

    def accessor(self, index):
        acc = self.gltf['accessors'][index]
        view = self.gltf['bufferViews'][acc['bufferView']]
        fmt, size = _COMPONENTS[acc['componentType']]
        width = _WIDTH[acc['type']]
        stride = view.get('byteStride', size * width)
        base = self.bin_start + view.get('byteOffset', 0) + acc.get('byteOffset', 0)
        values = [struct.unpack_from('<' + fmt * width, self.data, base + i * stride)
                  for i in range(acc['count'])]
        if not acc.get('normalized'):
            return values
        scale = _NORMALIZED_MAX[acc['componentType']]
        return [tuple(v / scale for v in value) for value in values]

    def world_meshes(self):
        """(nome nodo, matrice mondo, mesh) per ogni nodo con una mesh."""
        out = []

        def walk(index, parent):
            node = self.gltf['nodes'][index]
            matrix = _mul(parent, _local_matrix(node))
            if 'mesh' in node:
                out.append((node.get('name'), matrix, self.gltf['meshes'][node['mesh']]))
            for child in node.get('children', []):
                walk(child, matrix)

        scene = self.gltf['scenes'][self.gltf.get('scene', 0)]
        for root in scene['nodes']:
            walk(root, _IDENTITY)
        return out

    def material_name(self, index):
        if index is None:
            return None
        return self.gltf['materials'][index].get('name', f'#{index}')

    def triangles(self):
        for _, matrix, mesh in self.world_meshes():
            for prim in mesh['primitives']:
                points = [_apply(matrix, p) for p in self.accessor(prim['attributes']['POSITION'])]
                indices = ([i[0] for i in self.accessor(prim['indices'])]
                           if 'indices' in prim else list(range(len(points))))
                material = prim.get('material')
                for k in range(0, len(indices) - 2, 3):
                    yield points[indices[k]], points[indices[k + 1]], points[indices[k + 2]], material


_IDENTITY = [[1 if r == c else 0 for c in range(4)] for r in range(4)]


def _mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _local_matrix(node):
    if 'matrix' in node:
        m = node['matrix']
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    tx, ty, tz = node.get('translation', [0, 0, 0])
    x, y, z, w = node.get('rotation', [0, 0, 0, 1])
    sx, sy, sz = node.get('scale', [1, 1, 1])
    rot = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
           [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
           [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    t = (tx, ty, tz)
    return [[rot[r][0] * sx, rot[r][1] * sy, rot[r][2] * sz, t[r]] for r in range(3)] + [[0, 0, 0, 1]]


def _apply(m, p):
    return tuple(sum(m[r][c] * p[c] for c in range(3)) + m[r][3] for r in range(3))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def info(glb):
    gltf = glb.gltf
    triangle_count = {}
    for mesh in gltf['meshes']:
        for prim in mesh['primitives']:
            count = gltf['accessors'][prim['indices']]['count'] // 3 if 'indices' in prim else 0
            key = prim.get('material')
            triangle_count[key] = triangle_count.get(key, 0) + count
    print('Materiali (indice, nome, colore base, texture, triangoli):')
    for i, mat in enumerate(gltf.get('materials', [])):
        pbr = mat.get('pbrMetallicRoughness', {})
        color = [round(v, 3) for v in pbr.get('baseColorFactor', [1, 1, 1, 1])]
        texture = 'texture' if 'baseColorTexture' in pbr else '-'
        print(f'  {i:3} {mat.get("name")!r:45} {color} {texture} {triangle_count.get(i, 0)}')

    print('\nIngombri dei nodi (coordinate mondo):')
    overall_lo, overall_hi = [float('inf')] * 3, [float('-inf')] * 3
    for name, matrix, mesh in glb.world_meshes():
        lo, hi = [float('inf')] * 3, [float('-inf')] * 3
        materials = set()
        for prim in mesh['primitives']:
            acc = gltf['accessors'][prim['attributes']['POSITION']]
            scale = _NORMALIZED_MAX.get(acc['componentType'], 1) if acc.get('normalized') else 1
            amin = [v / scale for v in acc['min']]
            amax = [v / scale for v in acc['max']]
            materials.add(glb.material_name(prim.get('material')))
            for cx in (amin[0], amax[0]):
                for cy in (amin[1], amax[1]):
                    for cz in (amin[2], amax[2]):
                        p = _apply(matrix, (cx, cy, cz))
                        lo = [min(a, b) for a, b in zip(lo, p)]
                        hi = [max(a, b) for a, b in zip(hi, p)]
        overall_lo = [min(a, b) for a, b in zip(overall_lo, lo)]
        overall_hi = [max(a, b) for a, b in zip(overall_hi, hi)]
        print(f'  {name!r}: min={[round(v, 3) for v in lo]} max={[round(v, 3) for v in hi]} '
              f'materiali={sorted(m for m in materials if m)}')
    print(f'\nTotale: min={[round(v, 3) for v in overall_lo]} max={[round(v, 3) for v in overall_hi]}')


def ray(glb, origin, direction):
    best = None
    for a, b, c, material in glb.triangles():
        e1, e2 = _sub(b, a), _sub(c, a)
        p = _cross(direction, e2)
        det = _dot(e1, p)
        if abs(det) < 1e-12:
            continue
        inv = 1 / det
        t0 = _sub(origin, a)
        u = _dot(t0, p) * inv
        if u < 0 or u > 1:
            continue
        q = _cross(t0, e1)
        v = _dot(direction, q) * inv
        if v < 0 or u + v > 1:
            continue
        t = _dot(e2, q) * inv
        if t > 1e-6 and (best is None or t < best[0]):
            normal = _cross(e1, e2)
            length = _dot(normal, normal) ** 0.5 or 1
            normal = tuple(n / length for n in normal)
            if _dot(normal, direction) > 0:
                normal = tuple(-n for n in normal)
            best = (t, material, normal)
    if best is None:
        print('Nessun punto colpito.')
        return
    t, material, normal = best
    point = [round(origin[i] + direction[i] * t, 3) for i in range(3)]
    print(json.dumps({'position': point, 'normal': [round(n, 2) for n in normal],
                      'material': glb.material_name(material)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p_info = sub.add_parser('info', help='materiali e ingombri')
    p_info.add_argument('file')
    p_ray = sub.add_parser('ray', help='primo punto colpito da un raggio')
    p_ray.add_argument('file')
    p_ray.add_argument('--origin', type=float, nargs=3, required=True)
    p_ray.add_argument('--direction', type=float, nargs=3, required=True)
    args = parser.parse_args()

    glb = Glb(args.file)
    if args.command == 'info':
        info(glb)
    else:
        ray(glb, tuple(args.origin), tuple(args.direction))


if __name__ == '__main__':
    main()
