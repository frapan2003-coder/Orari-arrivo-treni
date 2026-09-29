#!/usr/bin/env python3
"""
tracker.py
Fa UNA fotografia del tabellone ARRIVI di una stazione (ViaggiaTreno) e la
accoda a data/raw_log.csv. Orari in ora italiana, ritardo solo in italiano.
"""

import csv
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BASE_URL = "http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno"
STATION_NAME = os.environ.get("STAZIONE", "Chieri")
ROME = ZoneInfo("Europe/Rome")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RAW_LOG_PATH = os.path.join(DATA_DIR, "raw_log.csv")
STATION_CACHE_PATH = os.path.join(DATA_DIR, "station_code.txt")

RAW_HEADER = [
    "rilevamento_locale",       # ora italiana del controllo, es. 2026-09-28 08:30:01
    "data_riferimento",         # data italiana del controllo
    "numero_treno",
    "categoria",
    "origine",
    "orario_arrivo_previsto",
    "ritardo_minuti",
    "ritardo_testo",            # solo italiano, es. "ritardo 5 min."
    "binario_previsto",
    "binario_effettivo",
    "in_stazione",
    "provvedimento_codice",     # 0 normale, 1 soppresso, 2 soppresso parzialmente/limitato
    "provvedimento_descrizione",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9",
    "Referer": "http://www.viaggiatreno.it/infomobilita/index.jsp",
}

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def solo_italiano(testo):
    """'ritardo 5 min. / delay 5 min. / ...' -> 'ritardo 5 min.'"""
    if isinstance(testo, list):
        testo = " / ".join(str(x) for x in testo if x)
    if not testo:
        return ""
    return html.unescape(str(testo).split(" / ")[0]).strip()


def utc_to_locale(iso_utc):
    """'2026-09-28T06:30:01+00:00' -> '2026-09-28 08:30:01' (ora italiana)."""
    return datetime.fromisoformat(iso_utc).astimezone(ROME).strftime("%Y-%m-%d %H:%M:%S")


def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} da {url}\nRisposta del server: {body[:300]!r}", file=sys.stderr)
        raise


def http_get_json(url, timeout=15):
    raw = http_get(url, timeout)
    return json.loads(raw) if raw.strip() else None


def get_station_code(name):
    if os.path.exists(STATION_CACHE_PATH):
        with open(STATION_CACHE_PATH, encoding="utf-8") as f:
            cached = f.read().strip()
            if cached:
                return cached
    raw = http_get(f"{BASE_URL}/autocompletaStazione/{urllib.parse.quote(name)}").strip()
    candidates = []
    for line in raw.splitlines():
        if "|" in line:
            label, code = line.split("|", 1)
            candidates.append((label.strip(), code.strip()))
    if not candidates:
        raise RuntimeError(f"Nessuna stazione trovata per '{name}': {raw!r}")
    exact = [c for c in candidates if c[0].upper() == name.upper()]
    chosen = exact[0] if exact else candidates[0]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATION_CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(chosen[1])
    return chosen[1]


def js_style_timestamp(now_utc=None):
    """Formato richiesto da arrivi/partenze (come new Date().toString() in Italia)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    rome = now_utc.astimezone(ROME)
    off = int(rome.utcoffset().total_seconds() // 60)
    sign = "+" if off >= 0 else "-"
    off = abs(off)
    tz = "Ora legale dell'Europa centrale" if rome.utcoffset().total_seconds() == 7200 \
        else "Ora solare dell'Europa centrale"
    return (f"{_WEEKDAYS[rome.weekday()]} {_MONTHS[rome.month - 1]} {rome.day:02d} "
            f"{rome.year} {rome.hour:02d}:{rome.minute:02d}:{rome.second:02d} "
            f"GMT{sign}{off // 60:02d}{off % 60:02d} ({tz})")


def fetch_arrivals(station_code):
    when = urllib.parse.quote(js_style_timestamp(), safe="")
    return http_get_json(f"{BASE_URL}/arrivi/{station_code}/{when}") or []


def migrate_raw_log():
    """Se raw_log.csv ha ancora il vecchio formato (ora UTC, ritardo in 9 lingue),
    lo converte una volta sola al nuovo formato senza perdere righe."""
    if not os.path.exists(RAW_LOG_PATH):
        return
    with open(RAW_LOG_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == RAW_HEADER:
            return
        old = list(reader)
    new_rows = []
    for r in old:
        if "poll_timestamp_utc" not in r:
            continue
        new_rows.append({
            "rilevamento_locale": utc_to_locale(r["poll_timestamp_utc"]),
            "data_riferimento": utc_to_locale(r["poll_timestamp_utc"])[:10],
            "numero_treno": r["numero_treno"],
            "categoria": r["categoria"],
            "origine": r["origine"],
            "orario_arrivo_previsto": r["orario_arrivo_previsto"],
            "ritardo_minuti": r["ritardo_minuti_dichiarato"],
            "ritardo_testo": solo_italiano(r["compRitardo"]),
            "binario_previsto": r["binario_previsto"],
            "binario_effettivo": r["binario_effettivo"],
            "in_stazione": r["in_stazione"],
            "provvedimento_codice": "1" if r.get("soppresso") == "True" else "0",
            "provvedimento_descrizione": "",
        })
    with open(RAW_LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RAW_HEADER)
        w.writeheader()
        w.writerows(new_rows)
    print(f"Migrato raw_log.csv al nuovo formato ({len(new_rows)} righe).")


def ensure_raw_log():
    os.makedirs(DATA_DIR, exist_ok=True)
    migrate_raw_log()
    if not os.path.exists(RAW_LOG_PATH):
        with open(RAW_LOG_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(RAW_HEADER)


def compatta_ultimo_rilevamento_per_treno():
    """Riduce raw_log.csv a UNA riga per treno per giorno: l'ultimo
    rilevamento in cui il treno è comparso nel tabellone (che sia
    'in_stazione' True o False). L'unica eccezione è il campo
    provvedimento: una volta rilevato soppresso/limitato (codice 1 o 2),
    resta congelato per sempre, anche se un controllo successivo mostrasse
    di nuovo lo stato 'normale' (0)."""
    if not os.path.exists(RAW_LOG_PATH):
        return
    with open(RAW_LOG_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if reader.fieldnames != RAW_HEADER:
            return  # verrà gestito da migrate_raw_log() alla prossima run

    latest = {}
    for r in rows:
        key = (r["data_riferimento"], r["numero_treno"], r["orario_arrivo_previsto"])
        if key not in latest:
            latest[key] = dict(r)
        else:
            prev = latest[key]
            merged = dict(r)  # parti dai valori più recenti...
            if prev.get("provvedimento_codice") in ("1", "2"):
                # ...ma congela per sempre la soppressione già rilevata
                merged["provvedimento_codice"] = prev["provvedimento_codice"]
                merged["provvedimento_descrizione"] = prev["provvedimento_descrizione"]
            latest[key] = merged

    ordered = sorted(latest.values(),
                      key=lambda r: (r["data_riferimento"], r["orario_arrivo_previsto"], r["numero_treno"]))

    with open(RAW_LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RAW_HEADER)
        w.writeheader()
        w.writerows(ordered)


def main():
    ensure_raw_log()
    now = datetime.now(timezone.utc).astimezone(ROME)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    day = now.strftime("%Y-%m-%d")

    try:
        arrivals = fetch_arrivals(get_station_code(STATION_NAME))
    except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as e:
        print(f"Errore durante il fetch: {e}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for t in arrivals:
        rows.append([
            stamp, day, t.get("numeroTreno"),
            t.get("categoria") or t.get("categoriaDescrizione"),
            t.get("origine"), t.get("compOrarioArrivo"), t.get("ritardo"),
            solo_italiano(t.get("compRitardo")),
            t.get("binarioProgrammatoArrivoDescrizione"),
            t.get("binarioEffettivoArrivoDescrizione"),
            t.get("inStazione"),
            t.get("provvedimento", 0),
            solo_italiano(t.get("subTitle")),
        ])
    with open(RAW_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    compatta_ultimo_rilevamento_per_treno()
    print(f"[{stamp}] Registrati {len(rows)} treni nel tabellone arrivi.")


if __name__ == "__main__":
    main()


