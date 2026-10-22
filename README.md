# syncuro-models

Modelli 3D dei veicoli per l'app Syncuro, serviti via
[jsDelivr](https://www.jsdelivr.com):

```
https://cdn.jsdelivr.net/gh/Davencode/syncuro-models@<tag>/catalog.json
https://cdn.jsdelivr.net/gh/Davencode/syncuro-models@<tag>/models/<id>.glb
```

L'app usa sempre un tag fisso (es. `v0.1.0`): una modifica al repository
arriva agli utenti solo quando l'app punta al nuovo tag.

## Struttura

- `catalog.json`: per ogni modello, le auto che rappresenta (marca, modello,
  anni), il file, il materiale della carrozzeria, l'inquadratura iniziale, i
  punti dei componenti e l'attribuzione.
- `models/`: i file `.glb` ottimizzati, chiamati `<marca>_<modello>_<generazione>.glb`.
- `CREDITS.md`: autore e licenza di ogni modello. Va aggiornato insieme al
  catalogo.

Ogni modello ha la propria licenza (vedi `CREDITS.md`); il repository non ha
una licenza unica. Sono ammesse solo CC0 e CC BY 4.0.

## Aggiungere un modello

1. Scarica il `.glb` originale e verifica la licenza (vedi la guida
   `docs/modelli-3d.md` nel repository dell'app).
2. Ottimizzalo:

   ```sh
   npx @gltf-transform/cli@4 optimize originale.glb models/<id>.glb \
     --compress quantize --texture-compress webp --texture-size 1024 \
     --simplify false --palette false
   ```

   `--palette false` è necessario: altrimenti il materiale della carrozzeria
   viene fuso con gli altri e non si può più ricolorare. Niente Draco o
   Meshopt: richiederebbero decoder scaricati da internet e il modello non
   funzionerebbe offline.
3. Aggiungi la voce in `catalog.json` e la riga in `CREDITS.md`.
4. Crea un nuovo tag (es. `v0.2.0`) e aggiorna il tag usato dall'app.
