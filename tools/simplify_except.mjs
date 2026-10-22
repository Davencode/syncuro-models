// Semplifica tutte le mesh tranne quelle con i materiali indicati
// (con '!' davanti: solo quelle).
// Uso: node simplify_except.mjs in.glb out.glb [!]body[,altro] [ratio] [error] [uv]
//
// uv: materiali senza texture di cui tenere le coordinate UV (es. `plate`,
// su cui l'app disegna la targa). Agli altri materiali senza texture le UV
// vengono tolte: non servono e pesano.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { weld, prune, dedup, simplifyPrimitive } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';

const [input, output, keepList, ratio = '0.1', error = '0.001', uvList = ''] = process.argv.slice(2);
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
const keepUv = new Set(uvList.split(',').filter(Boolean));
const hasTextures = (material) =>
  material != null &&
  [
    material.getBaseColorTexture(),
    material.getNormalTexture(),
    material.getOcclusionTexture(),
    material.getEmissiveTexture(),
    material.getMetallicRoughnessTexture(),
  ].some((texture) => texture != null);
for (const mesh of doc.getRoot().listMeshes()) {
  for (const prim of mesh.listPrimitives()) {
    const material = prim.getMaterial();
    if (hasTextures(material) || keepUv.has(material?.getName())) continue;
    for (const semantic of prim.listSemantics()) {
      if (semantic.startsWith('TEXCOORD_')) prim.setAttribute(semantic, null);
    }
  }
}
// keepAttributes: le UV scelte sopra restano anche senza texture.
await doc.transform(prune({ keepAttributes: true }));
await io.write(output, doc);
console.log(`triangoli: ${Math.round(before)} -> ${Math.round(after)}`);
