#!/usr/bin/env python3
"""
generate_report.py
Elabora data/raw_log.csv (le fotografie ripetute del tabellone arrivi) e
produce, per la giornata indicata (default: oggi UTC):

  - data/reports/report_YYYY-MM-DD.csv   -> dettaglio per treno
  - data/summary.csv                      -> riga aggregata per giorno,
                                              accodata (è quella che legge
                                              la dashboard index.html)

Logica: per ogni treno, prendiamo l'ULTIMA fotografia in cui compare nel
tabellone nella giornata come proxy del ritardo "finale" all'arrivo
(quando un treno arriva ed esce dal tabellone, l'ultimo valore registrato
è la stima più vicina all'orario reale di arrivo). Non è un dato certificato
al 100%, ma è la miglior approssimazione ottenibile da questa fonte pubblica
senza credenziali speciali.
"""

import csv
import os
import sys
import statistics
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RAW_LOG_PATH = os.path.join(DATA_DIR, "raw_log.csv")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
SUMMARY_PATH = os.path.join(DATA_DIR, "summary.csv")


def load_rows_for_day(target_day):
    if not os.path.exists(RAW_LOG_PATH):
        return []
    with open(RAW_LOG_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r["data_riferimento"] == target_day]


def build_daily_detail(rows):
    """Raggruppa per numero treno, tiene l'ultima fotografia disponibile."""
    latest_by_train = {}
    for r in rows:
        key = (r["numero_treno"], r["orario_arrivo_previsto"])
        # l'ultima riga letta per lo stesso treno sovrascrive la precedente
        latest_by_train[key] = r

    detail = []
    for (numero_treno, orario_previsto), r in latest_by_train.items():
        try:
            ritardo = int(r["ritardo_minuti_dichiarato"])
        except (ValueError, TypeError):
            ritardo = None
        detail.append({
            "numero_treno": numero_treno,
            "categoria": r["categoria"],
            "origine": r["origine"],
            "orario_arrivo_previsto": orario_previsto,
            "ritardo_minuti": ritardo,
            "ultimo_rilevamento_utc": r["poll_timestamp_utc"],
            "binario_previsto": r["binario_previsto"],
            "binario_effettivo": r["binario_effettivo"],
            "soppresso": r["soppresso"],
        })

    detail.sort(key=lambda d: (d["orario_arrivo_previsto"] or ""))
    return detail


def write_daily_detail(target_day, detail):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"report_{target_day}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "numero_treno", "categoria", "origine", "orario_arrivo_previsto",
            "ritardo_minuti", "ultimo_rilevamento_utc",
            "binario_previsto", "binario_effettivo", "soppresso",
        ])
        writer.writeheader()
        writer.writerows(detail)
    return path


def append_summary(target_day, detail):
    valid_delays = [d["ritardo_minuti"] for d in detail
                    if d["ritardo_minuti"] is not None and d["soppresso"] != "True"]
    n_treni = len(detail)
    n_soppressi = sum(1 for d in detail if d["soppresso"] == "True")
    ritardo_medio = round(statistics.mean(valid_delays), 1) if valid_delays else ""
    ritardo_mediano = round(statistics.median(valid_delays), 1) if valid_delays else ""
    ritardo_massimo = max(valid_delays) if valid_delays else ""
    puntuali = sum(1 for d in valid_delays if d <= 5)  # entro 5 min = "in orario"

    file_exists = os.path.exists(SUMMARY_PATH)
    with open(SUMMARY_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "data", "n_treni_osservati", "n_soppressi",
                "ritardo_medio_min", "ritardo_mediano_min",
                "ritardo_massimo_min", "treni_puntuali_entro_5min",
            ])
        writer.writerow([
            target_day, n_treni, n_soppressi,
            ritardo_medio, ritardo_mediano, ritardo_massimo, puntuali,
        ])


def main():
    target_day = sys.argv[1] if len(sys.argv) > 1 else \
        datetime.now(timezone.utc).strftime("%Y-%m-%d")

    rows = load_rows_for_day(target_day)
    if not rows:
        print(f"Nessun dato trovato per {target_day}.")
        return

    detail = build_daily_detail(rows)
    path = write_daily_detail(target_day, detail)
    append_summary(target_day, detail)
    print(f"Report giornaliero scritto in {path} ({len(detail)} treni).")
    print(f"Riepilogo aggiornato in {SUMMARY_PATH}.")


if __name__ == "__main__":
    main()
