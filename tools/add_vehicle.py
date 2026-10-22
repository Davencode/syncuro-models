#!/usr/bin/env python3
"""Prepara un modello 3D scaricato e lo aggiunge al catalogo, in automatico.

  python3 tools/add_vehicle.py ~/Downloads/auto.glb --make Fiat --model Tipo --years 2016-2026

Passi: licenza, triangoli invertiti, ruote e muso, vernice, tetto in vetro,
semplificazione, punti dei componenti, targhe, anteprima, catalogo e crediti.
Alla fine stampa un riepilogo e il percorso dell'anteprima (un'immagine con
quattro inquadrature): se va bene, pubblica con `tools/publish.sh vX.Y.Z`.

Le scelte automatiche si correggono in `vehicles/<id>.json` (vedi README),
poi si rilancia. Richiede Node (npx) e Google Chrome per l'anteprima.
"""

import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

from add_plates import add_plates  # noqa: E402
from fix_winding import fix_winding  # noqa: E402
from glb_tool import Glb, _apply  # noqa: E402
from set_material import set_material  # noqa: E402

ALLOWED_LICENSES = {'CC-BY-4.0': ('cc attribution', 'cc-by-4.0', 'creativecommons.org/licenses/by/4.0'),
                    'CC0-1.0': ('cc0', 'publicdomain/zero')}
TIRE = re.compile(r'tire|tyre|pneu|gomma|rubber|reifen', re.I)
HIDDEN = re.compile(r'brake|freio|freno|disc|disco|caliper|pinza|interior|interno|\bint\b|seat|sedil|'
                    r'leather|engine|motor|mechanic|dashboard|speaker|wood', re.I)
GLASS = re.compile(r'glass|vidro|vetro|window|glas|vitre|cristal', re.I)
PAINT = re.compile(r'paint|pintura|carroz|vernice|body|carpaint|car_paint', re.I)
NOT_PAINT = re.compile(r'plastic|chrome|cromad|rim|roda|tyre|tire|pneu|glass|vidro|window|light|farol|'
                       r'plate|targa|rubber|interior|interno', re.I)
PLATE_PART = re.compile(r'plate|targa|licen[cs]e|matric', re.I)
PLATE_HOLDER = re.compile(r'plate|targa|licen|matric|plastic|plastico', re.I)
LIGHT = re.compile(r'light|farol|faro|lamp|head', re.I)


def log(message):
    print(message, flush=True)


# --- Lettura del modello --------------------------------------------------------

class Model:
    """Parti del modello con ingombri e materiali, in coordinate mondo."""

    def __init__(self, path):
        self.glb = Glb(path)
        g = self.glb.gltf
        self.materials = [m.get('name', f'#{i}') for i, m in enumerate(g.get('materials', []))]
        self.material_info = g.get('materials', [])
        self.parts = []  # (nome nodo, materiali, min, max, triangoli)
        for name, matrix, mesh in self.glb.world_meshes():
            lo, hi = [math.inf] * 3, [-math.inf] * 3
            mats, tris = set(), 0
            for prim in mesh['primitives']:
                acc = g['accessors'][prim['attributes']['POSITION']]
                scale = {5122: 32767, 5120: 127, 5123: 65535, 5121: 255}.get(acc['componentType'], 1) \
                    if acc.get('normalized') else 1
                amin = [v / scale for v in acc['min']]
                amax = [v / scale for v in acc['max']]
                for cx in (amin[0], amax[0]):
                    for cy in (amin[1], amax[1]):
                        for cz in (amin[2], amax[2]):
                            p = _apply(matrix, (cx, cy, cz))
                            lo = [min(a, b) for a, b in zip(lo, p)]
                            hi = [max(a, b) for a, b in zip(hi, p)]
                if 'material' in prim:
                    mats.add(self.materials[prim['material']])
                count = g['accessors'][prim['indices']]['count'] if 'indices' in prim else acc['count']
                tris += count // 3
            self.parts.append((name, mats, lo, hi, tris))

    def triangles_by_material(self):
        out = {}
        for _, mats, _, _, tris in self.parts:
            for m in mats:
                out[m] = out.get(m, 0) + tris // max(len(mats), 1)
        return out

    def is_glass(self, name):
        info = self.material_info[self.materials.index(name)] if name in self.materials else {}
        alpha = info.get('pbrMetallicRoughness', {}).get('baseColorFactor', [1, 1, 1, 1])[3]
        return bool(GLASS.search(name)) or alpha < 0.9 or info.get('alphaMode') == 'BLEND'

    def has_texture(self, name):
        info = self.material_info[self.materials.index(name)]
        return 'baseColorTexture' in info.get('pbrMetallicRoughness', {})


class Raycaster:
    """Raggi paralleli agli assi, con una griglia per non testare tutti i
    triangoli a ogni raggio."""

    CELL = 0.05

    def __init__(self, glb):
        self.tris = list(glb.triangles())
        self.names = [m.get('name', f'#{i}') for i, m in enumerate(glb.gltf.get('materials', []))]
        self.grids = {}

    def _grid(self, axis):
        if axis not in self.grids:
            u, v = [k for k in range(3) if k != axis]
            grid = {}
            for i, (a, b, c, _) in enumerate(self.tris):
                u0, u1 = min(a[u], b[u], c[u]), max(a[u], b[u], c[u])
                v0, v1 = min(a[v], b[v], c[v]), max(a[v], b[v], c[v])
                for cu in range(math.floor(u0 / self.CELL), math.floor(u1 / self.CELL) + 1):
                    for cv in range(math.floor(v0 / self.CELL), math.floor(v1 / self.CELL) + 1):
                        grid.setdefault((cu, cv), []).append(i)
            self.grids[axis] = (u, v, grid)
        return self.grids[axis]

    def cast(self, origin, axis, sign):
        """Primo punto colpito da un raggio lungo [axis] (0, 1, 2) nel verso [sign]."""
        u, v, grid = self._grid(axis)
        cell = (math.floor(origin[u] / self.CELL), math.floor(origin[v] / self.CELL))
        d = [0.0, 0.0, 0.0]
        d[axis] = float(sign)
        best = None
        for i in grid.get(cell, ()):
            a, b, c, mat = self.tris[i]
            e1 = [b[k] - a[k] for k in range(3)]
            e2 = [c[k] - a[k] for k in range(3)]
            p = [d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0]]
            det = sum(e1[k] * p[k] for k in range(3))
            if abs(det) < 1e-12:
                continue
            t0 = [origin[k] - a[k] for k in range(3)]
            uu = sum(t0[k] * p[k] for k in range(3)) / det
            if uu < 0 or uu > 1:
                continue
            q = [t0[1] * e1[2] - t0[2] * e1[1], t0[2] * e1[0] - t0[0] * e1[2], t0[0] * e1[1] - t0[1] * e1[0]]
            vv = sum(d[k] * q[k] for k in range(3)) / det
            if vv < 0 or uu + vv > 1:
                continue
            t = sum(e2[k] * q[k] for k in range(3)) / det
            if t > 1e-6 and (best is None or t < best[0]):
                n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
                length = math.sqrt(sum(x * x for x in n)) or 1
                n = [x / length for x in n]
                if sum(n[k] * d[k] for k in range(3)) > 0:
                    n = [-x for x in n]
                best = (t, mat, n)
        if best is None:
            return None
        t, mat, n = best
        point = [origin[k] + d[k] * t for k in range(3)]
        return {'position': [round(x, 3) for x in point], 'normal': [round(x, 2) for x in n],
                'material': self.names[mat] if mat is not None else None}


# --- Passi ----------------------------------------------------------------------

def check_license(glb):
    extras = glb.gltf.get('asset', {}).get('extras', {})
    text = str(extras.get('license', ''))
    license_id = next((k for k, keys in ALLOWED_LICENSES.items() if any(s in text.lower() for s in keys)), None)
    if license_id is None:
        sys.exit(f'Licenza non ammessa: "{text or "assente"}". Servono CC BY 4.0 o CC0 '
                 '(niente Standard, Editorial, NC o ND).')

    def split(value):
        match = re.match(r'\s*(.*?)\s*\((https?://[^)]+)\)\s*$', value or '')
        return (match.group(1), match.group(2)) if match else ((value or '').strip(), None)

    author, author_url = split(extras.get('author'))
    if not author or not extras.get('source'):
        sys.exit('Mancano autore o fonte nei metadati: servono per l\'attribuzione.')
    return {'title': extras.get('title') or 'Senza titolo', 'author': author, 'authorUrl': author_url,
            'sourceUrl': extras['source'], 'license': license_id}


def _percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(fraction * len(ordered))))]


def find_wheels(model, tire_names, cx, half_width):
    """Assali e ruote dai vertici delle gomme, anche se le gomme sono unite in
    pochi pezzi: i vertici si addensano attorno ai due assali."""
    indices = {model.materials.index(n) for n in tire_names if n in model.materials}
    points = [p for a, b, c, mat in model.glb.triangles() if mat in indices for p in (a, b, c)
              if abs(p[0] - cx) > 0.3 * half_width]
    if len(points) < 100:
        sys.exit('Gomme non trovate: indica "tireMaterials" in vehicles/<id>.json.')
    bins = {}
    for p in points:
        bins[round(p[2] / 0.05)] = bins.get(round(p[2] / 0.05), 0) + 1
    ranked = sorted(bins, key=bins.get, reverse=True)
    first = ranked[0]
    second = next((b for b in ranked if abs(b - first) * 0.05 > 1.5), None)
    if second is None:
        sys.exit('Non trovo due assali: indica "tireMaterials" in vehicles/<id>.json.')
    axle, ys, xs = {}, [], []
    for peak in (first, second):
        # Il picco può cadere sul bordo della gomma: il centro della ruota è
        # il punto medio della sua estensione, ricalcolato due volte.
        zc = peak * 0.05
        for window in (0.6, 0.45):
            near = [p[2] for p in points if abs(p[2] - zc) < window]
            zc = (_percentile(near, 0.01) + _percentile(near, 0.99)) / 2
        axle[1 if zc > (first + second) * 0.025 else -1] = zc
        wheel = [p for p in points if abs(p[2] - zc) < 0.45]
        ys += [(_percentile([p[1] for p in wheel], 0.01) + _percentile([p[1] for p in wheel], 0.99)) / 2]
        xs.append(_percentile([abs(p[0] - cx) for p in wheel], 0.99))
    return axle, sum(ys) / len(ys), max(xs)


def plate_boxes(model, lo, hi):
    """Ingombro dei portatarga del modello vicino a ciascuna estremità (+Z e
    -Z), dai vertici: spesso un unico pezzo contiene entrambi i portatarga."""
    indices = {i for i, n in enumerate(model.materials) if PLATE_PART.search(n)}
    if not indices:
        return {}
    boxes = {}
    for a, b, c, mat in model.glb.triangles():
        if mat not in indices:
            continue
        for p in (a, b, c):
            for end, z in ((1, hi[2]), (-1, lo[2])):
                if abs(p[2] - z) < 0.4:
                    box = boxes.setdefault(end, [list(p), list(p)])
                    box[0] = [min(x, y) for x, y in zip(box[0], p)]
                    box[1] = [max(x, y) for x, y in zip(box[1], p)]
    return {end: box for end, box in boxes.items() if box[1][0] - box[0][0] > 0.3}


def analyse(model, override):
    parts = model.parts
    lo = [min(p[2][k] for p in parts) for k in range(3)]
    hi = [max(p[3][k] for p in parts) for k in range(3)]
    if hi[0] - lo[0] > (hi[2] - lo[2]) * 1.1:
        sys.exit('L\'auto è orientata lungo X: per ora sono supportati solo modelli lungo Z.')

    tire_names = override.get('tireMaterials') or [m for m in model.materials if TIRE.search(m)]
    if not tire_names:
        sys.exit('Gomme non trovate: indica "tireMaterials" in vehicles/<id>.json.')
    cx = (lo[0] + hi[0]) / 2
    axle, wheel_y, wheel_x = find_wheels(model, tire_names, cx, (hi[0] - lo[0]) / 2)
    # Il muso è dal lato con lo sbalzo più lungo.
    front = 1 if (hi[2] - axle[1]) > (axle[-1] - lo[2]) else -1

    paint = override.get('paintMaterial')
    if not paint:
        length = hi[2] - lo[2]
        best = None
        for name, tris in model.triangles_by_material().items():
            if model.is_glass(name) or model.has_texture(name) or NOT_PAINT.search(name):
                continue
            spans = [p for p in parts if name in p[1]]
            z0 = min(p[2][2] for p in spans)
            z1 = max(p[3][2] for p in spans)
            coverage = (z1 - z0) / length
            score = tris * coverage * (3 if PAINT.search(name) else 1)
            if coverage > 0.6 and (best is None or score > best[0]):
                best = (score, name)
        if best is None:
            sys.exit('Vernice non trovata: indica "paintMaterial" in vehicles/<id>.json.')
        paint = best[1]

    paint_top = max(p[3][1] for p in parts if paint in p[1])
    ground = lo[1]
    height = paint_top - ground
    roof = override.get('glassRoofNodes')
    if roof is None:
        roof = []
        width = hi[0] - lo[0]
        for name, mats, plo, phi, _ in parts:
            if not mats or not all(model.is_glass(m) for m in mats):
                continue
            centred = abs((plo[0] + phi[0]) / 2 - cx) < 0.15 * width
            high = plo[1] - ground > 0.8 * height
            flat = (phi[1] - plo[1]) < 0.15 * height
            between = min(axle.values()) - 0.2 < plo[2] and phi[2] < max(axle.values()) + 0.2
            long = (phi[2] - plo[2]) > 0.2 * (hi[2] - lo[2])
            if centred and high and flat and between and long:
                roof.append(name)
    return {'lo': lo, 'hi': hi, 'cx': cx, 'front': front, 'axle': axle, 'wheel_y': wheel_y,
            'wheel_x': wheel_x, 'paint': paint, 'paint_top': paint_top, 'ground': ground,
            'height': height, 'roof': roof,
            'plate_boxes': plate_boxes(model, lo, hi),
            'tires': tire_names, 'hidden': [m for m in model.materials if HIDDEN.search(m)]}


def run(cmd, cwd=TOOLS):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f'Comando fallito: {" ".join(cmd)}\n{result.stderr[-2000:]}')
    return result.stdout


def simplify(src, work, info):
    """Gomme senza normali e ridotte, poi freni, interni e meccanica ridotti."""
    current = src
    if info['tires']:
        step = os.path.join(work, 'tires.glb')
        run(['node', 'strip_normals.mjs', current, step, ','.join(info['tires'])])
        nxt = os.path.join(work, 'tires_s.glb')
        run(['node', 'simplify_except.mjs', step, nxt, '!' + ','.join(info['tires']), '0.08', '0.01'])
        current = nxt
    if info['hidden']:
        nxt = os.path.join(work, 'hidden_s.glb')
        run(['node', 'simplify_except.mjs', current, nxt, '!' + ','.join(info['hidden']), '0.1', '0.01'])
        current = nxt
    return current


def optimize(src, dst):
    run(['npx', '-y', '@gltf-transform/cli@4', 'optimize', src, dst, '--compress', 'quantize',
         '--texture-compress', 'webp', '--texture-size', '1024', '--palette', 'false',
         '--simplify', 'false', '--prune-attributes', 'false'])


def anchors(ray, info):
    lo, hi, cx, s = info['lo'], info['hi'], info['cx'], info['front']
    width = hi[0] - lo[0]
    front_axle, rear_axle = info['axle'][s], info['axle'][-s]
    front_end = hi[2] if s > 0 else lo[2]
    overhang = front_end - front_axle
    top = hi[1] + 1

    def down(x, z):
        hit = ray.cast((x, top, z), 1, -1)
        return hit and {'position': hit['position'], 'normal': hit['normal']}

    result = {
        'engine': down(cx, front_axle + overhang * 0.15),
        'battery': down(cx + 0.24 * width, front_axle + overhang * 0.45),
        'fluids': down(cx - 0.24 * width, front_axle + overhang * 0.45),
        'cabin': down(cx, (front_axle + rear_axle) / 2 - s * 0.1 * abs(front_axle - rear_axle)),
    }
    light = None
    for frac in (0.62, 0.58, 0.66, 0.54, 0.7, 0.5):
        hit = ray.cast((cx + 0.33 * width, info['ground'] + info['height'] * frac, front_end + s), 2, -s)
        if hit and (light is None or LIGHT.search(hit['material'] or '')):
            light = hit
            if LIGHT.search(hit['material'] or ''):
                break
    result['lights'] = light and {'position': light['position'], 'normal': light['normal']}
    for key in ('engine', 'battery', 'fluids', 'cabin', 'lights'):
        if result[key] is None:
            sys.exit(f'Punto "{key}" non trovato: indicalo in "anchors" di vehicles/<id>.json.')
    wx = info['wheel_x'] + 0.02
    result['wheels'] = [
        {'position': [round(cx + side * wx, 3), round(info['wheel_y'], 3), round(info['axle'][end], 3)],
         'normal': [side, 0, 0]}
        for end in (s, -s) for side in (1, -1)
    ]
    return {k: (v if isinstance(v, list) else [v]) for k, v in result.items()}


def find_plate(ray, info, end):
    """Portatarga del muso (end=1) o della coda (end=-1): quello del modello se
    c'è un materiale apposito, altrimenti una zona piatta e verticale."""
    lo, hi, cx, s = info['lo'], info['hi'], info['cx'], info['front']
    out = s * end
    tip = (hi[2] if out > 0 else lo[2]) + out
    box = info['plate_boxes'].get(out)
    if box:
        plo, phi = box
        px, py = (plo[0] + phi[0]) / 2, (plo[1] + phi[1]) / 2
        hit = ray.cast((px, py, tip), 2, -out)
        if hit:
            n = hit['normal']
            return (f'{px:.3f},{py:.3f},{hit["position"][2] + out * 0.008:.3f}:'
                    f'{n[0]:.2f},{n[1]:.2f},{n[2]:.2f}')
    hits = []
    y = info['ground'] + 0.15 * info['height']
    while y < info['ground'] + 0.75 * info['height']:
        hit = ray.cast((cx, y, tip), 2, -out)
        if hit:
            hits.append((y, hit))
        y += 0.01
    # Tratti consecutivi verticali, alla stessa profondità e dello stesso materiale.
    runs, current = [], []
    for y, hit in hits:
        continues = (current and abs(hit['normal'][2]) >= 0.85
                     and abs(hit['position'][2] - current[-1][1]['position'][2]) <= 0.006
                     and hit['material'] == current[-1][1]['material'])
        if not continues:
            if current:
                runs.append(current)
            current = [(y, hit)] if abs(hit['normal'][2]) >= 0.85 else []
        else:
            current.append((y, hit))
    if current:
        runs.append(current)
    best = None
    for run_ in runs:
        height = run_[-1][0] - run_[0][0]
        if height < 0.09:
            continue
        cy = (run_[0][0] + run_[-1][0]) / 2
        cz = sum(h['position'][2] for _, h in run_) / len(run_)
        edges = [ray.cast((cx + side * 0.24, cy, tip), 2, -out) for side in (1, -1)]
        if any(e is None or abs(e['position'][2] - cz) > 0.03 for e in edges):
            continue
        score = -abs(height - 0.12) + (0.1 if PLATE_HOLDER.search(run_[0][1]['material'] or '') else 0)
        if best is None or score > best[0]:
            n = [sum(h['normal'][k] for _, h in run_) / len(run_) for k in range(3)]
            best = (score, (cx, cy, cz + out * 0.006), n)
    if best is None:
        return None
    _, (px, py, pz), n = best
    return f'{px:.3f},{py:.3f},{pz:.3f}:{n[0]:.2f},{n[1]:.2f},{n[2]:.2f}'


PREVIEW_JS = r"""
const paint = %(paint)s, plateMaterial = %(plate)s;
function drawPlate(text) {
  const c = document.createElement('canvas'); c.width = 1040; c.height = 220;
  const g = c.getContext('2d');
  g.fillStyle = '#f4f4f2'; g.fillRect(0, 0, 1040, 220);
  g.fillStyle = '#1d3e9e'; g.fillRect(0, 0, 110, 220); g.fillRect(930, 0, 110, 220);
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillStyle = '#ffffff'; g.font = 'bold 64px Arial'; g.fillText('I', 55, 165);
  g.fillStyle = '#111111'; g.font = 'bold 150px Arial'; g.fillText(text, 520, 118, 780);
  return c.toDataURL('image/png');
}
for (const viewer of document.querySelectorAll('model-viewer')) {
  viewer.addEventListener('load', async () => {
    for (const m of viewer.model.materials) {
      if (m.name === paint) {
        m.pbrMetallicRoughness.setBaseColorFactor('#b3202a');
        m.pbrMetallicRoughness.setMetallicFactor(0.35);
        m.pbrMetallicRoughness.setRoughnessFactor(0.3);
        if (m.setClearcoatFactor) { m.setClearcoatFactor(1); m.setClearcoatRoughnessFactor(0.03); }
      }
    }
    if (plateMaterial) {
      const texture = await viewer.createTexture(drawPlate('AB 123 CD'));
      for (const m of viewer.model.materials) {
        if (m.name === plateMaterial) m.pbrMetallicRoughness.baseColorTexture.setTexture(texture);
      }
    }
  });
}
"""


def preview(glb_path, info, model_anchors, plate_material, out_png):
    work = os.path.dirname(out_png)
    shutil.copy(glb_path, os.path.join(work, 'preview.glb'))
    base = 0 if info['front'] > 0 else 180
    views = [(base + 35, 72, 105, True), (base + 90, 80, 100, False),
             (base + 15, 85, 60, False), (base + 195, 82, 60, False)]
    spots = ''.join(
        f'<button slot="hotspot-{k}-{i}" data-position="{a["position"][0]}m {a["position"][1]}m '
        f'{a["position"][2]}m" data-normal="{a["normal"][0]}m {a["normal"][1]}m {a["normal"][2]}m" '
        f'class="hs"></button>'
        for k, items in model_anchors.items() for i, a in enumerate(items))
    viewers = ''.join(
        f'<model-viewer src="preview.glb" camera-orbit="{t}deg {p}deg {r}%" environment-image="neutral" '
        f'exposure="1.1" shadow-intensity="1" interaction-prompt="none">{spots if hs else ""}'
        '</model-viewer>' for t, p, r, hs in views)
    html = ('<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#0a0e13;display:grid;'
            'grid-template-columns:1fr 1fr;grid-template-rows:50vh 50vh}model-viewer{width:100%;height:100%}'
            '.hs{width:14px;height:14px;border-radius:50%;border:2px solid #fff;background:#ffb547;padding:0}'
            '</style><script type="module" '
            'src="https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>'
            + viewers + '<script>' + PREVIEW_JS % {'paint': json.dumps(info['paint']),
                                                   'plate': json.dumps(plate_material)} + '</script>')
    with open(os.path.join(work, 'preview.html'), 'w') as f:
        f.write(html)
    server = subprocess.Popen([sys.executable, '-I', '-m', 'http.server', '8799', '--bind', '127.0.0.1',
                               '--directory', work], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        run(['node', 'preview_shot.mjs', 'http://127.0.0.1:8799/preview.html', out_png, '1400', '1000',
             '25000'])
    finally:
        server.terminate()


def unique_file(model_id, glb_path):
    """Un file pubblicato non si cambia: se esiste già con un altro contenuto
    si usa un nome nuovo (_v2, _v3...)."""
    name, n = f'{model_id}.glb', 1
    while True:
        path = os.path.join(ROOT, 'models', name)
        if not os.path.exists(path) or open(path, 'rb').read() == open(glb_path, 'rb').read():
            return f'models/{name}'
        n += 1
        name = f'{model_id}_v{n}.glb'


def update_catalog(entry, credits_row):
    path = os.path.join(ROOT, 'catalog.json')
    catalog = json.load(open(path))
    old = next((m for m in catalog['models'] if m['id'] == entry['id']), None)
    if old and old['file'] != entry['file'] and os.path.exists(os.path.join(ROOT, old['file'])):
        os.remove(os.path.join(ROOT, old['file']))
    catalog['models'] = [m for m in catalog['models'] if m['id'] != entry['id']] + [entry]
    text = json.dumps(catalog, indent=2, ensure_ascii=False)
    text = re.sub(r'\[\s+(-?[\d.]+),\s+(-?[\d.]+),\s+(-?[\d.]+)\s+\]', r'[\1, \2, \3]', text)
    with open(path, 'w') as f:
        f.write(text + '\n')
    credits = os.path.join(ROOT, 'CREDITS.md')
    lines = [line for line in open(credits).read().rstrip().split('\n')
             if not (old and f'`{old["file"]}`' in line)]
    with open(credits, 'w') as f:
        f.write('\n'.join(lines) + '\n' + credits_row + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source')
    parser.add_argument('--make', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--years', required=True, help='es. 2016-2026')
    parser.add_argument('--id', help='es. fiat_tipo (predefinito: marca_modello)')
    args = parser.parse_args()

    model_id = args.id or re.sub(r'[^a-z0-9]+', '_', f'{args.make}_{args.model}'.lower()).strip('_')
    year_from, year_to = (int(y) for y in args.years.split('-'))
    override_path = os.path.join(ROOT, 'vehicles', f'{model_id}.json')
    override = json.load(open(override_path)) if os.path.exists(override_path) else {}
    work = os.path.join(ROOT, 'build', model_id)
    os.makedirs(work, exist_ok=True)

    log(f'1/8 licenza')
    attribution = check_license(Glb(args.source))
    log(f'    {attribution["title"]} di {attribution["author"]}, {attribution["license"]}')

    log('2/8 triangoli invertiti')
    fixed = os.path.join(work, 'fixed.glb')
    flipped, total = fix_winding(args.source, fixed)
    log(f'    girati {flipped} su {total}')

    log('3/8 analisi')
    model = Model(fixed)
    info = analyse(model, override)
    log(f'    muso verso {"+Z" if info["front"] > 0 else "-Z"}, vernice "{info["paint"]}", '
        f'gomme {info["tires"]}, tetto in vetro {info["roof"] or "no"}')
    if info['roof']:
        roofed = os.path.join(work, 'roof.glb')
        set_material(fixed, roofed, [f'{n}={info["paint"]}' for n in info['roof']])
        fixed = roofed

    log('4/8 semplificazione e ottimizzazione')
    reduced = simplify(fixed, work, info)
    optimized = os.path.join(work, 'optimized.glb')
    optimize(reduced, optimized)
    final_model = Glb(optimized)
    names = [m.get('name') for m in final_model.gltf['materials']]
    if info['paint'] not in names:
        sys.exit(f'L\'ottimizzazione ha perso il materiale "{info["paint"]}".')

    log('5/8 punti dei componenti')
    ray = Raycaster(final_model)
    model_anchors = anchors(ray, info)
    for key, value in override.get('anchors', {}).items():
        model_anchors[key] = value

    log('6/8 targhe')
    plates = []
    for end, label in ((1, 'frontPlate'), (-1, 'rearPlate')):
        spec = override.get(label) or find_plate(ray, info, end)
        log(f'    {label}: {spec or "non trovata"}')
        if spec:
            plates.append(spec)
    final = os.path.join(work, 'final.glb')
    if plates and not override.get('noPlates'):
        add_plates(optimized, final, plates)
    else:
        shutil.copy(optimized, final)
    plate_material = 'plate' if plates and not override.get('noPlates') else None

    log('7/8 anteprima')
    preview_png = os.path.join(work, 'preview.png')
    preview(final, info, model_anchors, plate_material, preview_png)

    log('8/8 catalogo e crediti')
    file = unique_file(model_id, final)
    shutil.copy(final, os.path.join(ROOT, file))
    changes = 'Corretti i triangoli invertiti; ' if flipped else ''
    if info['roof']:
        changes += 'tetto in vetro reso in tinta carrozzeria; '
    changes += 'semplificati pneumatici, freni e interni; geometria quantizzata, texture WebP 1024 px'
    if plates:
        changes += '; aggiunte targhe'
    entry = {'id': model_id, 'make': args.make, 'model': args.model, 'yearFrom': year_from,
             'yearTo': year_to, 'file': file, 'paintMaterial': info['paint']}
    if plate_material:
        entry['plateMaterial'] = plate_material
    entry['initialOrbit'] = override.get('initialOrbit', f'{35 if info["front"] > 0 else 215}deg 72deg 105%')
    entry['anchors'] = model_anchors
    entry['attribution'] = {**{k: v for k, v in attribution.items() if v},
                            'retrievedOn': time.strftime('%Y-%m-%d'),
                            'changes': changes + '; colore della carrozzeria e targa modificati nell\'app.'}
    author = (f'[{attribution["author"]}]({attribution["authorUrl"]})' if attribution['authorUrl']
              else attribution['author'])
    license_link = ('[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)'
                    if attribution['license'] == 'CC-BY-4.0'
                    else '[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)')
    update_catalog(entry, f'| `{file}` | [{attribution["title"]}]({attribution["sourceUrl"]}) | {author} '
                          f'| {license_link} | {entry["attribution"]["retrievedOn"]} | {changes} |')

    size = os.path.getsize(os.path.join(ROOT, file)) / 1e6
    triangles = sum(1 for _ in final_model.triangles())
    log(f'\nFatto: {file} ({size:.1f} MB, {triangles} triangoli).')
    log(f'Anteprima: {preview_png}')
    log('Se va bene: committa e pubblica con tools/publish.sh vX.Y.Z. '
        f'Altrimenti correggi vehicles/{model_id}.json e rilancia.')


if __name__ == '__main__':
    main()
