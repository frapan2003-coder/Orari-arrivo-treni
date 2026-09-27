#!/usr/bin/env python3
"""
tracker.py
Interroga le API (non ufficiali) di ViaggiaTreno per il tabellone ARRIVI
di una stazione, e registra su un file CSV "grezzo" lo stato di ogni treno
al momento del controllo (ritardo dichiarato, orario previsto, ecc.).

Va lanciato ogni N minuti (tipicamente ogni 10) da uno scheduler esterno
(GitHub Actions, cron, Task Scheduler...). Ogni esecuzione fa UNA sola
fotografia del tabellone e la accoda al file di log.

Il calcolo del "ritardo finale" giorno per giorno viene fatto a parte da
generate_report.py, analizzando la sequenza di fotografie.
"""

import csv
import os
import sys
import time
from datetime import datetime, timezone
import urllib.request
import urllib.error
import json

BASE_URL = "http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno"
STATION_NAME = os.environ.get("STAZIONE", "Chieri")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RAW_LOG_PATH = os.path.join(DATA_DIR, "raw_log.csv")
STATION_CACHE_PATH = os.path.join(DATA_DIR, "station_code.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrainDelayTracker/1.0)"
}


def http_get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        if not raw.strip():
            return None
        return json.loads(raw)


def get_station_code(name):
    """Cerca il codice stazione (es. S01700) a partire dal nome.
    Usa una cache locale per non doverlo richiedere ogni volta."""
    if os.path.exists(STATION_CACHE_PATH):
        with open(STATION_CACHE_PATH, "r", encoding="utf-8") as f:
            cached = f.read().strip()
            if cached:
                return cached

    url = f"{BASE_URL}/autocompletaStazione/{urllib.parse.quote(name)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8").strip()

    # Formato risposta: "NOME STAZIONE|CODICE\n" per ogni riga
    candidates = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        station_label, code = line.split("|", 1)
        candidates.append((station_label.strip(), code.strip()))

    if not candidates:
        raise RuntimeError(
            f"Nessuna stazione trovata per '{name}'. Risposta grezza: {raw!r}"
        )

    # Preferisci una corrispondenza esatta (case-insensitive) sul nome
    exact = [c for c in candidates if c[0].upper() == name.upper()]
    chosen = exact[0] if exact else candidates[0]

    with open(STATION_CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(chosen[1])

    print(f"Stazione '{name}' -> codice {chosen[1]} ({chosen[0]})")
    return chosen[1]


def fetch_arrivals(station_code, when_ms=None):
    """Scarica il tabellone arrivi per la stazione al timestamp indicato
    (default: adesso)."""
    if when_ms is None:
        when_ms = int(time.time() * 1000)
    url = f"{BASE_URL}/arrivi/{station_code}/{when_ms}"
    data = http_get_json(url)
    return data or []


def ensure_raw_log_header():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(RAW_LOG_PATH):
        with open(RAW_LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "poll_timestamp_utc",
                "data_riferimento",
                "numero_treno",
                "categoria",
                "origine",
                "orario_arrivo_previsto",
                "ritardo_minuti_dichiarato",
                "compRitardo",
                "binario_previsto",
                "binario_effettivo",
                "in_stazione",
                "soppresso",
            ])


def append_rows(rows):
    with open(RAW_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def main():
    ensure_raw_log_header()
    now = datetime.now(timezone.utc)
    poll_ts = now.isoformat(timespec="seconds")
    data_riferimento = now.strftime("%Y-%m-%d")

    try:
        code = get_station_code(STATION_NAME)
        arrivals = fetch_arrivals(code)
    except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as e:
        print(f"Errore durante il fetch: {e}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for t in arrivals:
        numero_treno = t.get("numeroTreno")
        categoria = t.get("categoria") or t.get("categoriaDescrizione")
        origine = t.get("origine")
        orario_previsto = t.get("compOrarioArrivo")
        ritardo = t.get("ritardo")
        comp_ritardo = t.get("compRitardo")
        if isinstance(comp_ritardo, list):
            comp_ritardo = " / ".join(str(x) for x in comp_ritardo if x)
        binario_previsto = t.get("binarioProgrammatoArrivoDescrizione")
        binario_effettivo = t.get("binarioEffettivoArrivoDescrizione")
        in_stazione = t.get("inStazione")
        soppresso = (t.get("provvedimento") == 1)

        rows.append([
            poll_ts,
            data_riferimento,
            numero_treno,
            categoria,
            origine,
            orario_previsto,
            ritardo,
            comp_ritardo,
            binario_previsto,
            binario_effettivo,
            in_stazione,
            soppresso,
        ])

    append_rows(rows)
    print(f"[{poll_ts}] Registrati {len(rows)} treni nel tabellone arrivi.")


if __name__ == "__main__":
    import urllib.parse
    main()
