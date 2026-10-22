// Raggi paralleli agli assi su un modello, molto più veloci che in Python.
// Carica il modello una volta, poi legge una richiesta per riga da stdin:
//   ox oy oz asse verso      (asse 0, 1, 2; verso 1 o -1)
// e risponde una riga JSON: {"position", "normal", "material"} oppure null.
// Uso: node raycast_server.mjs modello.glb
//
// Usa array compatti (Float32Array, Int32Array): con oggetti JavaScript
// piccoli un modello da un milione di triangoli esaurisce la memoria.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import readline from 'node:readline';

const CELL = 0.1;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(process.argv[2]);

// Prima passata: quanti triangoli.
const parts = [];
let total = 0;
for (const node of doc.getRoot().listNodes()) {
  const mesh = node.getMesh();
  if (!mesh) continue;
  for (const prim of mesh.listPrimitives()) {
    const position = prim.getAttribute('POSITION');
    // Solo triangoli: linee e punti (es. i bordi esportati da SketchUp) no.
    if (!position || prim.getMode() !== 4) continue;
    const indices = prim.getIndices();
    const count = Math.floor((indices ? indices.getCount() : position.getCount()) / 3);
    parts.push({ node, prim, position, indices, count });
    total += count;
  }
}

// Seconda passata: vertici in coordinate mondo, 9 numeri per triangolo.
const coords = new Float32Array(total * 9);
const materialIndex = new Int32Array(total);
const materialNames = [];
const materialIds = new Map();
let tri = 0;
const transformedByNode = new Map();
for (const { node, prim, position, indices, count } of parts) {
  // Più primitive possono condividere gli stessi vertici: li trasformiamo una
  // volta sola per nodo.
  let cache = transformedByNode.get(node);
  if (!cache) transformedByNode.set(node, (cache = new Map()));
  let world = cache.get(position);
  if (!world) {
    const m = node.getWorldMatrix();
    const n = position.getCount();
    world = new Float32Array(n * 3);
    const p = [0, 0, 0];
    for (let i = 0; i < n; i++) {
      position.getElement(i, p);
      world[i * 3] = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
      world[i * 3 + 1] = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
      world[i * 3 + 2] = m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14];
    }
    cache.set(position, world);
  }
  const name = prim.getMaterial()?.getName() ?? null;
  if (!materialIds.has(name)) {
    materialIds.set(name, materialNames.length);
    materialNames.push(name);
  }
  const id = materialIds.get(name);
  for (let t = 0; t < count; t++, tri++) {
    for (let k = 0; k < 3; k++) {
      const v = indices ? indices.getScalar(t * 3 + k) : t * 3 + k;
      coords[tri * 9 + k * 3] = world[v * 3];
      coords[tri * 9 + k * 3 + 1] = world[v * 3 + 1];
      coords[tri * 9 + k * 3 + 2] = world[v * 3 + 2];
    }
    materialIndex[tri] = id;
  }
}
transformedByNode.clear();

// Griglia per asse, in formato compatto: per ogni cella un intervallo in un
// unico Int32Array di indici di triangolo.
const grids = {};
function cellRange(i, u, v) {
  const o = i * 9;
  const u0 = Math.min(coords[o + u], coords[o + 3 + u], coords[o + 6 + u]);
  const u1 = Math.max(coords[o + u], coords[o + 3 + u], coords[o + 6 + u]);
  const v0 = Math.min(coords[o + v], coords[o + 3 + v], coords[o + 6 + v]);
  const v1 = Math.max(coords[o + v], coords[o + 3 + v], coords[o + 6 + v]);
  return [Math.floor(u0 / CELL), Math.floor(u1 / CELL), Math.floor(v0 / CELL), Math.floor(v1 / CELL)];
}
const key = (cu, cv) => (cu + 5000) * 10000 + (cv + 5000);
function grid(axis) {
  if (grids[axis]) return grids[axis];
  const [u, v] = [0, 1, 2].filter((k) => k !== axis);
  const counts = new Map();
  for (let i = 0; i < tri; i++) {
    const [cu0, cu1, cv0, cv1] = cellRange(i, u, v);
    for (let cu = cu0; cu <= cu1; cu++) {
      for (let cv = cv0; cv <= cv1; cv++) {
        const k = key(cu, cv);
        counts.set(k, (counts.get(k) ?? 0) + 1);
      }
    }
  }
  const start = new Map();
  let offset = 0;
  for (const [k, c] of counts) {
    start.set(k, [offset, 0]);
    offset += c;
  }
  const items = new Int32Array(offset);
  for (let i = 0; i < tri; i++) {
    const [cu0, cu1, cv0, cv1] = cellRange(i, u, v);
    for (let cu = cu0; cu <= cu1; cu++) {
      for (let cv = cv0; cv <= cv1; cv++) {
        const entry = start.get(key(cu, cv));
        items[entry[0] + entry[1]++] = i;
      }
    }
  }
  grids[axis] = { u, v, start, items };
  return grids[axis];
}

function cast(origin, axis, sign) {
  const { u, v, start, items } = grid(axis);
  const entry = start.get(key(Math.floor(origin[u] / CELL), Math.floor(origin[v] / CELL)));
  if (!entry) return null;
  const d = [0, 0, 0];
  d[axis] = sign;
  let best = null;
  for (let j = entry[0]; j < entry[0] + entry[1]; j++) {
    const o = items[j] * 9;
    const a = [coords[o], coords[o + 1], coords[o + 2]];
    const e1 = [coords[o + 3] - a[0], coords[o + 4] - a[1], coords[o + 5] - a[2]];
    const e2 = [coords[o + 6] - a[0], coords[o + 7] - a[1], coords[o + 8] - a[2]];
    const p = [d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0]];
    const det = e1[0] * p[0] + e1[1] * p[1] + e1[2] * p[2];
    if (Math.abs(det) < 1e-12) continue;
    const t0 = [origin[0] - a[0], origin[1] - a[1], origin[2] - a[2]];
    const uu = (t0[0] * p[0] + t0[1] * p[1] + t0[2] * p[2]) / det;
    if (uu < 0 || uu > 1) continue;
    const q = [t0[1] * e1[2] - t0[2] * e1[1], t0[2] * e1[0] - t0[0] * e1[2], t0[0] * e1[1] - t0[1] * e1[0]];
    const vv = (d[0] * q[0] + d[1] * q[1] + d[2] * q[2]) / det;
    if (vv < 0 || uu + vv > 1) continue;
    const t = (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2]) / det;
    if (t > 1e-6 && (!best || t < best.t)) best = { t, i: items[j], e1, e2 };
  }
  if (!best) return null;
  let n = [
    best.e1[1] * best.e2[2] - best.e1[2] * best.e2[1],
    best.e1[2] * best.e2[0] - best.e1[0] * best.e2[2],
    best.e1[0] * best.e2[1] - best.e1[1] * best.e2[0],
  ];
  const len = Math.hypot(...n) || 1;
  n = n.map((x) => x / len);
  if (n[axis] * sign > 0) n = n.map((x) => -x);
  const round = (x, k) => Math.round(x * 10 ** k) / 10 ** k;
  return {
    position: origin.map((x, k) => round(x + d[k] * best.t, 3)),
    normal: n.map((x) => round(x, 2)),
    material: materialNames[materialIndex[best.i]],
  };
}

console.log('pronto');
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  const [ox, oy, oz, axis, sign] = line.trim().split(/\s+/).map(Number);
  console.log(JSON.stringify(cast([ox, oy, oz], axis, sign)));
}
