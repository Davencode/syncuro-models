#!/usr/bin/env python3
"""Assegna un altro materiale a delle parti del modello, per nome del nodo.

Esempio (tetto in vetro della Peugeot 208 reso in tinta con la carrozzeria):

  python3 tools/set_material.py originale.glb modificato.glb Object_85=Carro_Pintura

I nomi dei nodi e dei materiali si trovano con `tools/glb_tool.py info`.
"""

import json
import struct
import sys


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    src, dst, assignments = sys.argv[1], sys.argv[2], sys.argv[3:]

    with open(src, 'rb') as f:
        data = f.read()
    json_length = struct.unpack_from('<I', data, 12)[0]
    gltf = json.loads(data[20:20 + json_length])
    materials = {m.get('name'): i for i, m in enumerate(gltf.get('materials', []))}

    for assignment in assignments:
        node_name, material_name = assignment.split('=', 1)
        if material_name not in materials:
            sys.exit(f'Materiale sconosciuto: {material_name}')
        nodes = [n for n in gltf['nodes'] if n.get('name') == node_name and 'mesh' in n]
        if not nodes:
            sys.exit(f'Nodo con mesh sconosciuto: {node_name}')
        for node in nodes:
            mesh_index = node['mesh']
            users = sum(1 for n in gltf['nodes'] if n.get('mesh') == mesh_index)
            if users > 1:
                # La mesh è condivisa: ne facciamo una copia solo per questo nodo.
                gltf['meshes'].append(json.loads(json.dumps(gltf['meshes'][mesh_index])))
                mesh_index = node['mesh'] = len(gltf['meshes']) - 1
            for primitive in gltf['meshes'][mesh_index]['primitives']:
                primitive['material'] = materials[material_name]
        print(f'{node_name}: {material_name}')

    chunk = json.dumps(gltf, separators=(',', ':')).encode()
    chunk += b' ' * ((4 - len(chunk) % 4) % 4)
    rest = data[20 + json_length:]
    total = 12 + 8 + len(chunk) + len(rest)
    with open(dst, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(chunk), 0x4E4F534A))
        f.write(chunk)
        f.write(rest)


if __name__ == '__main__':
    main()
