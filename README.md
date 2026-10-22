# syncuro-models

Modelli 3D dei veicoli per l'app Syncuro, serviti via
[jsDelivr](https://www.jsdelivr.com).

## Come li legge l'app

1. `index.json` (da `main`) indica la versione corrente del catalogo:
   `https://cdn.jsdelivr.net/gh/Davencode/syncuro-models@main/index.json`
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
2. **Ottimizzalo** in `models/<marca>_<modello>_<generazione>.glb`:

   ```sh
   npx @gltf-transform/cli@4 optimize originale.glb models/<id>.glb \
     --compress quantize --texture-compress webp --texture-size 1024 \
     --simplify false --palette false
   ```

   `--palette false` è necessario, altrimenti il materiale della carrozzeria
   viene fuso con gli altri e non si può più ricolorare. Niente Draco o
   Meshopt: richiederebbero decoder scaricati da internet e il modello non
   funzionerebbe offline.
3. **Analizzalo** con `tools/glb_tool.py`:

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

4. **Calcola i punti** sparando raggi verso la superficie: dall'alto per
   cofano e tetto, di lato all'altezza dei mozzi per le ruote, dal davanti
   per i fari.

   ```sh
   python3 tools/glb_tool.py ray models/<id>.glb --origin X 10 Z --direction 0 -1 0
   ```

   Il risultato (`position`, `normal`) va in `anchors`. I punti delle ruote
   vanno spostati di qualche centimetro verso l'esterno, così la spalla
   dello pneumatico non li copre.
5. **Aggiungi la voce** in `catalog.json` e la riga in `CREDITS.md`, poi
   committa.
6. **Pubblica**: `tools/publish.sh v0.2.0`.
