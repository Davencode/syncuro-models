// Toglie le normali (e le UV) alle primitive dei materiali indicati, così
// i vertici si possono unire e semplificare. Uso: in out materiale[,altro]
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune } from '@gltf-transform/functions';
const [input, output, list] = process.argv.slice(2);
const names = new Set(list.split(','));
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(input);
for (const mesh of doc.getRoot().listMeshes()) {
  for (const prim of mesh.listPrimitives()) {
    if (!names.has(prim.getMaterial()?.getName())) continue;
    for (const s of prim.listSemantics()) if (s !== 'POSITION') prim.setAttribute(s, null);
  }
}
await doc.transform(prune());
await io.write(output, doc);
