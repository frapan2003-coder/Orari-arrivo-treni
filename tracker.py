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
    "cod_origine",              # codice stazione di origine del treno (serve per il controllo incrociato)
    "millis_partenza",          # timestamp (ms) di mezzanotte del giorno di partenza (idem)
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
            "cod_origine": "",
            "millis_partenza": "",
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


def fetch_andamento(cod_origine, numero_treno, millis_partenza):
    """Dettaglio dell'intero percorso di un treno (solo per la giornata in
    corso: questa API non restituisce dati per i giorni passati)."""
    if not cod_origine or not millis_partenza:
        return None
    url = f"{BASE_URL}/andamentoTreno/{cod_origine}/{numero_treno}/{millis_partenza}"
    try:
        return http_get_json(url)
    except Exception as e:
        print(f"Controllo incrociato fallito per il treno {numero_treno}: {e}", file=sys.stderr)
        return None


def verifica_arrivo_a_chieri(row):
    """Per un treno sparito dal tabellone senza essere mai stato visto
    'in_stazione', chiede all'API il dettaglio dell'intero percorso e
    cerca la fermata a Chieri. Ritorna un dict di campi da aggiornare, o
    None se non si può ancora concludere nulla (si riprova al giro dopo)."""
    data = fetch_andamento(row.get("cod_origine"), row["numero_treno"], row.get("millis_partenza"))
    if not data:
        return None

    if data.get("provvedimento") == 1:
        return {
            "provvedimento_codice": "1",
            "provvedimento_descrizione": solo_italiano(data.get("subTitle")) or "Treno soppresso",
        }

    fermate = data.get("fermate") or []
    target = next((f for f in fermate if STATION_NAME.upper() in (f.get("stazione") or "").upper()), None)
    if target is None:
        return None  # fermata non trovata nel percorso: riprova al giro dopo

    if target.get("actualFermataType") == 3:
        return {
            "provvedimento_codice": "2",
            "provvedimento_descrizione": solo_italiano(data.get("subTitle")) or "Treno limitato/parzialmente soppresso",
        }

    arrivo_reale = target.get("arrivoReale")
    if not arrivo_reale:
        return None  # non ancora transitato da Chieri: riprova al giro dopo

    ritardo = target.get("ritardoArrivo")
    if ritardo is None:
        programmata = target.get("programmata") or target.get("arrivo_teorico")
        ritardo = round((arrivo_reale - programmata) / 60000) if programmata else 0
    ritardo = max(0, ritardo)
    testo = "in orario" if ritardo == 0 else f"ritardo {ritardo} min."

    return {
        "in_stazione": "True",
        "ritardo_minuti": str(ritardo),
        "ritardo_testo": testo,
    }


def leggi_tutte_le_righe():
    if not os.path.exists(RAW_LOG_PATH):
        return []
    with open(RAW_LOG_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != RAW_HEADER:
            return []  # verrà gestito da migrate_raw_log() alla prossima run
        return list(reader)


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
    now_hhmm = now.strftime("%H:%M")

    try:
        arrivals = fetch_arrivals(get_station_code(STATION_NAME))
    except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as e:
        print(f"Errore durante il fetch: {e}", file=sys.stderr)
        sys.exit(1)

    rows = []
    numeri_nel_tabellone = set()
    for t in arrivals:
        numero = str(t.get("numeroTreno"))
        numeri_nel_tabellone.add(numero)
        rows.append({
            "rilevamento_locale": stamp, "data_riferimento": day,
            "numero_treno": numero,
            "categoria": t.get("categoria") or t.get("categoriaDescrizione"),
            "origine": t.get("origine"),
            "orario_arrivo_previsto": t.get("compOrarioArrivo"),
            "ritardo_minuti": t.get("ritardo"),
            "ritardo_testo": solo_italiano(t.get("compRitardo")),
            "binario_previsto": t.get("binarioProgrammatoArrivoDescrizione"),
            "binario_effettivo": t.get("binarioEffettivoArrivoDescrizione"),
            "in_stazione": t.get("inStazione"),
            "provvedimento_codice": str(t.get("provvedimento", 0)),
            "provvedimento_descrizione": solo_italiano(t.get("subTitle")),
            "cod_origine": t.get("codOrigine"),
            "millis_partenza": t.get("dataPartenzaTreno"),
        })

    # Controllo incrociato: treni di oggi già usciti dal tabellone, con
    # orario previsto già passato, che non sono mai stati visti arrivati
    # né già segnalati soppressi/limitati -> verifica diretta sul treno.
    correzioni = []
    for r in leggi_tutte_le_righe():
        if r["data_riferimento"] != day:
            continue
        if r["in_stazione"] == "True":
            continue
        if r.get("provvedimento_codice") in ("1", "2"):
            continue
        if r["numero_treno"] in numeri_nel_tabellone:
            continue  # ancora nel tabellone: nessun bisogno di verificare ora
        orario_previsto = r.get("orario_arrivo_previsto") or ""
        if orario_previsto and orario_previsto > now_hhmm:
            continue  # non ancora dovuto
        esito = verifica_arrivo_a_chieri(r)
        if esito:
            riga = dict(r)
            riga.update(esito)
            riga["rilevamento_locale"] = stamp
            correzioni.append(riga)

    with open(RAW_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RAW_HEADER)
        w.writerows(rows)
        w.writerows(correzioni)

    compatta_ultimo_rilevamento_per_treno()
    msg = f"[{stamp}] Registrati {len(rows)} treni nel tabellone arrivi."
    if correzioni:
        msg += f" Confermati via controllo incrociato: {len(correzioni)}."
    print(msg)


if __name__ == "__main__":
    main()

