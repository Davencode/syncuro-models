// Alleggerisce le parti indicate di un modello troppo pesante: toglie le
// normali (i pezzi con facce staccate non si possono unire né semplificare),
// unisce i vertici, semplifica e ricalcola normali morbide.
// Uso: node lighten.mjs in.glb out.glb materiale[,altro] [ratio] [error]
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { weld, simplifyPrimitive, normals, prune } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';

const [input, output, list, ratio = '0.25', error = '0.001'] = process.argv.slice(2);
if (!list) {
  console.error('Uso: node lighten.mjs in.glb out.glb materiale[,altro] [ratio] [error]');
  process.exit(1);
}
const names = new Set(list.split(','));
await MeshoptSimplifier.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(input);

const targets = [];
for (const mesh of doc.getRoot().listMeshes()) {
  for (const prim of mesh.listPrimitives()) {
    if (!names.has(prim.getMaterial()?.getName())) continue;
    prim.setAttribute('NORMAL', null);
    targets.push(prim);
  }
}
await doc.transform(weld());
let before = 0, after = 0;
const count = (p) => (p.getIndices()?.getCount() ?? p.getAttribute('POSITION').getCount()) / 3;
for (const prim of targets) {
  before += count(prim);
  simplifyPrimitive(prim, { simplifier: MeshoptSimplifier, ratio: Number(ratio), error: Number(error) });
  after += count(prim);
}
// Normali ricalcolate solo dove mancano: le altre parti restano com'erano.
await doc.transform(normals({ overwrite: false }), prune({ keepAttributes: true }));
await io.write(output, doc);
console.log(`triangoli alleggeriti: ${Math.round(before)} -> ${Math.round(after)}`);
