// Semplifica tutte le mesh tranne quelle con i materiali indicati
// (con '!' davanti: solo quelle).
// Uso: node simplify_except.mjs in.glb out.glb [!]body[,altro] [ratio] [error]
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { weld, prune, dedup, simplifyPrimitive } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';

const [input, output, keepList, ratio = '0.1', error = '0.001'] = process.argv.slice(2);
if (!keepList) {
  console.error('Uso: node tools/simplify_except.mjs in.glb out.glb [!]materiale[,altro] [ratio] [error]');
  process.exit(1);
}
const only = keepList.startsWith('!');
const names = new Set(keepList.replace(/^!/, '').split(','));
const shouldSimplify = (name) => (only ? names.has(name) : !names.has(name));

await MeshoptSimplifier.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(input);
await doc.transform(dedup(), weld());

let before = 0, after = 0;
const count = (prim) => (prim.getIndices()?.getCount() ?? prim.getAttribute('POSITION').getCount()) / 3;
for (const mesh of doc.getRoot().listMeshes()) {
  for (const prim of mesh.listPrimitives()) {
    const tris = count(prim);
    before += tris;
    if (shouldSimplify(prim.getMaterial()?.getName())) {
      simplifyPrimitive(prim, { simplifier: MeshoptSimplifier, ratio: Number(ratio), error: Number(error) });
    }
    after += count(prim);
  }
}
await doc.transform(prune());
await io.write(output, doc);
console.log(`triangoli: ${Math.round(before)} -> ${Math.round(after)}`);
