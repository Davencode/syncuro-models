# syncuro-models

Modelli 3D dei veicoli per l'app Syncuro, serviti via
[jsDelivr](https://www.jsdelivr.com).

## Come li legge l'app

1. `index.json` (da `main`) indica la versione corrente del catalogo:
   `https://raw.githubusercontent.com/Davencode/syncuro-models/main/index.json`.
   Non passa da jsDelivr: per un branch jsDelivr tiene in cache il commit per
   ore, anche dopo un purge, e l'app vedrebbe la versione vecchia.
2. Il catalogo di quella versione:
   `https://cdn.jsdelivr.net/gh/Davencode/syncuro-models@<tag>/catalog.json`
3. Solo il modello dell'auto dell'utente:
   `https://cdn.jsdelivr.net/gh/Davencode/syncuro-models@<tag>/models/<file>.glb`

L'app tiene in cache catalogo e modelli. Senza rete usa l'ultima versione
nota. Pubblicando una nuova versione, gli utenti la ricevono senza
aggiornare l'app.

**Un file pubblicato in `models/` non si modifica mai.** L'app lo tiene in
cache per nome: se un modello cambia, va salvato con un nome nuovo (es.
`volkswagen_golf_8_v2.glb`) e aggiornato in `catalog.json`.

## Struttura

- `index.json`: versione corrente; si aggiorna solo con `tools/publish.sh`.
- `catalog.json`: per ogni modello, le auto che rappresenta (marca, modello,
  anni), il file, il materiale della carrozzeria, l'inquadratura iniziale, i
  punti dei componenti e l'attribuzione.
- `models/`: i file `.glb` ottimizzati.
- `CREDITS.md`: autore e licenza di ogni modello.
- `tools/`: analisi dei modelli e pubblicazione.

Ogni modello ha la propria licenza (vedi `CREDITS.md`); il repository non ha
una licenza unica. Sono ammesse solo CC0 e CC BY 4.0: l'app scarta le altre.

## Aggiungere un modello

1. **Scarica il `.glb` originale** e verifica la licenza (vedi la guida
   `docs/modelli-3d.md` nel repository dell'app).
2. **Controllalo** in un visualizzatore: se sulla vernice compaiono schegge
   chiare a triangoli, l'orientamento dei triangoli è incoerente. Correggilo
   prima di ottimizzare:

   ```sh
   python3 tools/fix_winding.py originale.glb corretto.glb
   ```

   Per cambiare il materiale di una parte (es. un tetto in vetro da rendere
   in tinta con la carrozzeria, così l'app lo ricolora):

   ```sh
   python3 tools/set_material.py corretto.glb modificato.glb Object_85=Carro_Pintura
   ```

   Se le gomme non si semplificano (normali sfaccettate che impediscono di
   unire i vertici), togli loro le normali prima di semplificare: la gomma
   nera non ne risente.

   ```sh
   node tools/strip_normals.mjs modificato.glb senza_normali.glb Carro_Pneu1
   ```

3. **Se è troppo pesante** (molto più di 300k triangoli), semplificalo in
   modo selettivo: le parti secondarie in modo forte, la carrozzeria solo
   dove la forma non cambia. Una semplificazione uniforme ammacca la
   vernice, perché i riflessi mostrano ogni deformazione.

   ```sh
   (cd tools && npm install)
   node tools/simplify_except.mjs corretto.glb passo1.glb body 0.05 0.005
   node tools/simplify_except.mjs passo1.glb ridotto.glb '!body' 0.3 0.0001
   ```

   Il terzo argomento è l'elenco dei materiali (`!` davanti: solo quelli),
   poi la quota di vertici da tenere, la tolleranza (frazione dell'ingombro)
   e i materiali senza texture di cui tenere le UV (es. `plate`).

   Le superfici lucide e grandi (vernice, tetto nero lucido, pannelli scuri
   dietro i vetri) mostrano ogni deformazione nei riflessi: lasciale intatte
   o con tolleranza minima (`0.00005`). Per la Corsa:

   ```sh
   K=body,black_shiny,black_matt,black,interior,plate,glass,d_glass
   node tools/simplify_except.mjs corretto.glb p1.glb $K 0.05 0.005 plate
   node tools/simplify_except.mjs p1.glb p2.glb '!black_matt,interior,plate,glass,d_glass' 0.2 0.0005 plate
   node tools/simplify_except.mjs p2.glb ridotto.glb '!black_shiny,black' 0.5 0.00005 plate
   ```

   Poi, nell'ottimizzazione, aggiungi `--prune-attributes false` per non
   perdere le UV della targa. Ricontrolla sempre l'aspetto confrontandolo con
   l'originale.
4. **Ottimizzalo** in `models/<marca>_<modello>_<generazione>.glb`:

   ```sh
   npx @gltf-transform/cli@4 optimize originale.glb models/<id>.glb \
     --compress quantize --texture-compress webp --texture-size 1024 \
     --simplify false --palette false
   ```

   `--palette false` è necessario, altrimenti il materiale della carrozzeria
   viene fuso con gli altri e non si può più ricolorare. Niente Draco o
   Meshopt: richiederebbero decoder scaricati da internet e il modello non
   funzionerebbe offline.
5. **Analizzalo** con `tools/glb_tool.py`:

   ```sh
   python3 tools/glb_tool.py info models/<id>.glb
   ```

   - **Orientamento**: dall'ingombro totale, l'asse più lungo è la lunghezza
     dell'auto e Y è l'altezza. Il muso è dal lato con lo sbalzo più lungo
     (le ruote anteriori sono più lontane dall'estremità).
   - **Carrozzeria**: il materiale con molti triangoli che copre tutto
     l'ingombro, di solito bianco o grigio senza texture.
   - **Inquadratura** (`initialOrbit`): l'angolo è misurato da +Z. Con il muso
     verso +Z, `35deg` mostra il tre quarti anteriore sinistro; con il muso
     verso -Z, `215deg`.

6. **Calcola i punti** sparando raggi verso la superficie: dall'alto per
   cofano e tetto, di lato all'altezza dei mozzi per le ruote, dal davanti
   per i fari.

   ```sh
   python3 tools/glb_tool.py ray models/<id>.glb --origin X 10 Z --direction 0 -1 0
   ```

   Il risultato (`position`, `normal`) va in `anchors`. I punti delle ruote
   vanno spostati di qualche centimetro verso l'esterno, così la spalla
   dello pneumatico non li copre.
7. **Aggiungi la voce** in `catalog.json` e la riga in `CREDITS.md`, poi
   committa.
8. **Pubblica**: `tools/publish.sh v0.2.0`.
