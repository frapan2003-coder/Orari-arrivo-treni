#!/usr/bin/env python3
"""
generate_report.py
Elabora data/raw_log.csv per una giornata e produce:
  - data/reports/report_YYYY-MM-DD.csv  -> un rigo per treno, con l'ESITO:
        arrivato   -> ritardo registrato nel momento in cui in_stazione=True
        non_arrivato -> non è mai comparso in_stazione=True in giornata;
                        si riporta l'ultimo rilevamento disponibile
        limitato/soppresso -> provvedimento_codice 1 o 2 (dato ufficiale
                        della fonte, indipendente da in_stazione)
  - data/summary.csv -> una riga aggregata per giorno (accodata)
"""

import csv
import os
import statistics
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RAW_LOG_PATH = os.path.join(DATA_DIR, "raw_log.csv")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
SUMMARY_PATH = os.path.join(DATA_DIR, "summary.csv")
ROME = ZoneInfo("Europe/Rome")

DETAIL_FIELDS = [
    "numero_treno", "categoria", "origine", "orario_arrivo_previsto",
    "esito", "ritardo_minuti", "ritardo_testo",
    "ultimo_rilevamento", "provvedimento",
]


def load_rows_for_day(target_day):
    if not os.path.exists(RAW_LOG_PATH):
        return []
    with open(RAW_LOG_PATH, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["data_riferimento"] == target_day]


def build_daily_detail(rows):
    by_train = {}
    for r in rows:
        key = (r["numero_treno"], r["orario_arrivo_previsto"])
        by_train.setdefault(key, []).append(r)

    detail = []
    for (numero_treno, orario_previsto), seq in by_train.items():
        seq.sort(key=lambda r: r["rilevamento_locale"])
        last = seq[-1]

        prov_codice = last.get("provvedimento_codice", "0")
        prov_desc = last.get("provvedimento_descrizione", "")

        arrivati = [r for r in seq if r["in_stazione"] == "True"]

        if prov_codice in ("1", "2"):
            esito = "soppresso" if prov_codice == "1" else "limitato/parzialmente soppresso"
            ritardo_minuti = ""
            ritardo_testo = prov_desc or ("Treno soppresso" if prov_codice == "1" else "Treno limitato")
        elif arrivati:
            arrivo = arrivati[0]  # primo rilevamento in cui risulta in stazione
            esito = "arrivato"
            ritardo_minuti = arrivo["ritardo_minuti"]
            ritardo_testo = arrivo["ritardo_testo"]
        else:
            esito = "non_arrivato"
            ritardo_minuti = last["ritardo_minuti"]
            ritardo_testo = last["ritardo_testo"]

        detail.append({
            "numero_treno": numero_treno,
            "categoria": last["categoria"],
            "origine": last["origine"],
            "orario_arrivo_previsto": orario_previsto,
            "esito": esito,
            "ritardo_minuti": ritardo_minuti,
            "ritardo_testo": ritardo_testo,
            "ultimo_rilevamento": last["rilevamento_locale"],
            "provvedimento": prov_desc,
        })

    detail.sort(key=lambda d: (d["orario_arrivo_previsto"] or ""))
    return detail


def write_daily_detail(target_day, detail):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"report_{target_day}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        w.writeheader()
        w.writerows(detail)
    return path


SUMMARY_HEADER = [
    "data", "n_treni_osservati", "n_arrivati", "n_non_arrivati",
    "n_soppressi_o_limitati", "n_puntuali_sotto3", "n_ritardo_3_5",
    "n_ritardo_oltre5", "ritardo_medio_min", "ritardo_mediano_min",
    "ritardo_massimo_min",
]


def stats_for_day_detail(detail):
    arrivati = [d for d in detail if d["esito"] == "arrivato"]
    non_arrivati = [d for d in detail if d["esito"] == "non_arrivato"]
    soppressi = [d for d in detail if d["esito"] in ("soppresso", "limitato/parzialmente soppresso")]

    ritardi = [int(d["ritardo_minuti"]) for d in arrivati if d["ritardo_minuti"] not in ("", None)]
    ritardo_medio = round(statistics.mean(ritardi), 1) if ritardi else ""
    ritardo_mediano = round(statistics.median(ritardi), 1) if ritardi else ""
    ritardo_massimo = max(ritardi) if ritardi else ""

    n_puntuali = sum(1 for r in ritardi if r < 3)
    n_lieve = sum(1 for r in ritardi if 3 <= r <= 5)
    n_alto = sum(1 for r in ritardi if r > 5)

    return {
        "n_treni_osservati": len(detail),
        "n_arrivati": len(arrivati),
        "n_non_arrivati": len(non_arrivati),
        "n_soppressi_o_limitati": len(soppressi),
        "n_puntuali_sotto3": n_puntuali,
        "n_ritardo_3_5": n_lieve,
        "n_ritardo_oltre5": n_alto,
        "ritardo_medio_min": ritardo_medio,
        "ritardo_mediano_min": ritardo_mediano,
        "ritardo_massimo_min": ritardo_massimo,
    }


def rebuild_summary():
    """Ricostruisce data/summary.csv da zero leggendo TUTTI i report
    giornalieri già presenti in data/reports/. Se un file è in un formato
    vecchio/malformato (es. rimasto da una versione precedente dello
    script) viene semplicemente saltato con un avviso, invece di bloccare
    l'intera esecuzione."""
    if not os.path.isdir(REPORTS_DIR):
        return
    giorni = sorted(
        fn[len("report_"):-4]
        for fn in os.listdir(REPORTS_DIR)
        if fn.startswith("report_") and fn.endswith(".csv")
    )
    with open(SUMMARY_PATH, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(SUMMARY_HEADER)
        for giorno in giorni:
            with open(os.path.join(REPORTS_DIR, f"report_{giorno}.csv"),
                      newline="", encoding="utf-8") as f:
                detail = list(csv.DictReader(f))
            try:
                s = stats_for_day_detail(detail)
            except KeyError as e:
                print(f"Attenzione: report_{giorno}.csv in formato non valido "
                      f"(manca il campo {e}), lo salto. Verrà rigenerato alla "
                      f"prossima esecuzione se {giorno} è ancora in raw_log.csv.",
                      file=sys.stderr)
                continue
            w.writerow([giorno] + [s[k] for k in SUMMARY_HEADER[1:]])


def load_all_raw_rows():
    if not os.path.exists(RAW_LOG_PATH):
        return []
    with open(RAW_LOG_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    giorno_forzato = sys.argv[1] if len(sys.argv) > 1 else None

    rows_all = load_all_raw_rows()
    if not rows_all:
        print("Nessun dato trovato in raw_log.csv.")
        return

    oggi_locale = datetime.now(timezone.utc).astimezone(ROME).strftime("%Y-%m-%d")
    giorni_presenti = sorted({r["data_riferimento"] for r in rows_all if r.get("data_riferimento")})
    # Rigenera tutti i giorni conclusi (tutto tranne oggi, che è ancora in
    # corso) a ogni esecuzione: così è irrilevante A CHE ORA gira lo script,
    # ed eventuali file vecchi/corrotti vengono sempre riscritti da zero.
    giorni_da_generare = [g for g in giorni_presenti if g != oggi_locale]
    if giorno_forzato and giorno_forzato not in giorni_da_generare:
        giorni_da_generare.append(giorno_forzato)
        giorni_da_generare.sort()

    if not giorni_da_generare:
        print("Nessun giorno concluso da elaborare (ci sono solo dati di oggi).")
        return

    for giorno in giorni_da_generare:
        rows = [r for r in rows_all if r["data_riferimento"] == giorno]
        detail = build_daily_detail(rows)
        write_daily_detail(giorno, detail)

    rebuild_summary()
    print(f"Rigenerati {len(giorni_da_generare)} report giornalieri: {', '.join(giorni_da_generare)}")
    print(f"Riepilogo ricostruito in {SUMMARY_PATH}.")


if __name__ == "__main__":
    main()


