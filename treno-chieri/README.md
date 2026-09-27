# Monitoraggio ritardi treni — arrivi a Chieri

## Come attivarlo (5 passaggi, una tantum)

1. **Crea un repository GitHub** (gratuito): vai su github.com → New repository →
   dagli un nome (es. `ritardi-chieri`) → Public → Create repository.

2. **Carica questi file** nel repository, mantenendo la struttura di cartelle
   esattamente come sono (importante: `.github/workflows/monitor.yml` deve
   restare in quel percorso). Puoi trascinarli dalla pagina web del repository
   ("Add file" → "Upload files"), oppure con git da terminale.

3. **Attiva i permessi di scrittura per le Actions**:
   Settings del repository → Actions → General → in fondo, sezione
   "Workflow permissions" → seleziona "Read and write permissions" → Save.
   (Serve perché lo script deve poter salvare i dati raccolti nel repository.)

4. **Attiva GitHub Pages** (per la dashboard):
   Settings → Pages → sotto "Build and deployment" → Source: "Deploy from a
   branch" → Branch: `main`, cartella `/ (root)` → Save.
   Dopo un paio di minuti la dashboard sarà visibile su:
   `https://TUO-USERNAME.github.io/NOME-REPOSITORY/`
   Salvala tra i preferiti / sulla home del telefono: è il link che consulterai
   ogni giorno, si aggiorna da solo.

5. **Verifica che lo scheduling funzioni**:
   Vai nella tab "Actions" del repository, apri il workflow "Monitoraggio
   ritardi treni Chieri" e lancialo una volta a mano con "Run workflow" per
   controllare che non ci siano errori. Da quel momento partirà da solo ogni
   10 minuti.

## Cosa fa concretamente

- **`tracker.py`** — ogni 10 minuti scarica il tabellone arrivi di Chieri da
  ViaggiaTreno e ne salva una "fotografia" in `data/raw_log.csv`.
- **`generate_report.py`** — una volta al giorno (23:55 circa, orario
  italiano) elabora le fotografie della giornata e produce:
  - `data/reports/report_YYYY-MM-DD.csv` (dettaglio per treno)
  - una riga aggiunta a `data/summary.csv` (statistiche aggregate del giorno)
- **`index.html`** — la dashboard: legge i due file CSV sopra e mostra un
  grafico dell'andamento nel tempo più il dettaglio del giorno selezionato.
  Nessun file da scaricare: apri il link e vedi sempre i dati più recenti.

## Un'avvertenza importante sul dato di "ritardo"

ViaggiaTreno non fornisce un endpoint che dica esplicitamente "il treno X è
arrivato con Y minuti di ritardo" in modo definitivo — fornisce il ritardo
*stimato al momento della richiesta*, che si aggiorna mentre il treno si
avvicina alla stazione. Lo script usa come proxy del ritardo finale l'**ultimo
valore osservato prima che il treno sparisca dal tabellone**, che nella
stragrande maggioranza dei casi coincide con il ritardo reale all'arrivo (o è
molto vicino). Nei primi giorni di raccolta conviene controllare qualche caso
a campione confrontandolo con l'app ufficiale, per verificare che il dato
torni.

## Se vuoi cambiare stazione o intervallo di controllo

- Stazione: modifica la variabile d'ambiente `STAZIONE` nel workflow
  (`.github/workflows/monitor.yml`), oppure passa un nome diverso a
  `tracker.py`.
- Frequenza: modifica l'espressione cron `*/10 * * * *` nel workflow
  (es. `*/5 * * * *` per ogni 5 minuti — occhio ai limiti gratuiti di GitHub
  Actions su repository pubblici, comunque generosi per un uso come questo).
