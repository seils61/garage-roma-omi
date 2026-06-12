"""
Script 1: Estrazione dati OMI per Roma - categoria garage/box/posti auto

Scarica il dataset "valori.csv" dal repository pubblico ondata
(https://github.com/ondata/quotazioni-immobiliari-agenzia-entrate), che
raccoglie i dati OMI dell'Agenzia delle Entrate dal 2016 in formato CSV
pronto all'uso (fonte originale: "Agenzia Entrate - OMI").

Filtra per:
  - Comune = ROMA
  - Tipologia immobile = Autorimesse / Posti auto coperti (categoria C/6)
  - Solo il semestre più recente disponibile

Produce: omi_roma_garage.json
  Struttura: { "ZONA": {"compr_min": ..., "compr_max": ..., "descr": ...}, ... }

Da eseguire una volta e poi ogni ~6 mesi (quando l'Agenzia pubblica il
nuovo semestre OMI), tramite GitHub Actions schedulato.
"""

import csv
import io
import json
import os
import py7zr
import urllib.request

# URL del file 7z con tutti i valori OMI dal 2016 (repo ondata)
VALORI_7Z_URL = "https://github.com/ondata/quotazioni-immobiliari-agenzia-entrate/raw/master/data/valori.7z"

COMUNE_TARGET = "ROMA"

# Tipologie corrispondenti a garage/box/posti auto (categoria catastale C/6)
TIPOLOGIE_GARAGE = {
    "AUTORIMESSE",
    "POSTI AUTO COPERTI",
}

OUTPUT_FILE = "omi_roma_garage.json"


def download_and_extract():
    print("Download valori.7z ...")
    tmp_7z = "valori.7z"
    urllib.request.urlretrieve(VALORI_7Z_URL, tmp_7z)

    print("Estrazione...")
    with py7zr.SevenZipFile(tmp_7z, mode="r") as archive:
        archive.extractall(path=".")

    # Il file estratto si chiama valori.csv
    if not os.path.exists("valori.csv"):
        # cerca file csv estratto
        for f in os.listdir("."):
            if f.lower().endswith(".csv") and "valori" in f.lower():
                os.rename(f, "valori.csv")
                break

    os.remove(tmp_7z)
    print("OK: valori.csv pronto")


def estrai_roma_garage():
    rows = []
    with open("valori.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            comune = (row.get("Comune_descrizione") or "").strip().upper()
            tipologia = (row.get("Descr_Tipologia") or "").strip().upper()

            if comune != COMUNE_TARGET:
                continue
            if tipologia not in TIPOLOGIE_GARAGE:
                continue

            rows.append(row)

    if not rows:
        print("ATTENZIONE: nessuna riga trovata per Roma/garage. Verifica nomi colonne/valori.")
        return {}

    # Trova il semestre più recente (campo 'file' contiene es. QI_..._20242_VALORI_utf8.csv)
    def estrai_periodo(filename):
        # formato tipico: QI_xxxxxx_x_20242_VALORI_utf8.csv -> 20242 = anno 2024 semestre 2
        parts = filename.replace(".csv", "").split("_")
        for p in parts:
            if len(p) == 5 and p.isdigit():
                return int(p)
        return 0

    max_periodo = max(estrai_periodo(r["file"]) for r in rows)
    rows_recenti = [r for r in rows if estrai_periodo(r["file"]) == max_periodo]

    print(f"Periodo OMI più recente trovato: {max_periodo}")
    print(f"Righe garage/box a Roma nel periodo più recente: {len(rows_recenti)}")

    risultato = {}
    for r in rows_recenti:
        zona = r["Zona"].strip()
        try:
            compr_min = float(r["Compr_min"])
            compr_max = float(r["Compr_max"])
        except (ValueError, TypeError):
            continue

        # Se esistono più righe per la stessa zona (es. tipologie diverse),
        # teniamo il range più ampio (min più basso, max più alto)
        if zona not in risultato:
            risultato[zona] = {
                "compr_min": compr_min,
                "compr_max": compr_max,
                "descrizioni": set(),
                "fascia": r.get("Fascia", ""),
                "comune_amm": r.get("Comune_amm", ""),
                "periodo": max_periodo,
            }
        else:
            risultato[zona]["compr_min"] = min(risultato[zona]["compr_min"], compr_min)
            risultato[zona]["compr_max"] = max(risultato[zona]["compr_max"], compr_max)

        risultato[zona]["descrizioni"].add(r["Descr_Tipologia"].strip())

    # Convertiamo i set in liste per la serializzazione JSON
    for zona in risultato:
        risultato[zona]["descrizioni"] = sorted(risultato[zona]["descrizioni"])

    return risultato


def estrai_nomi_zone():
    """
    Estrae anche i nomi/descrizioni delle zone OMI di Roma dal file zone.csv,
    utili per il matching testuale con gli annunci (es. 'PRATI', 'EUR', ecc.)
    """
    zone_url = "https://github.com/ondata/quotazioni-immobiliari-agenzia-entrate/raw/master/data/zone.7z"
    tmp_7z = "zone.7z"
    print("Download zone.7z ...")
    urllib.request.urlretrieve(zone_url, tmp_7z)

    with py7zr.SevenZipFile(tmp_7z, mode="r") as archive:
        archive.extractall(path=".")

    if not os.path.exists("zone.csv"):
        for f in os.listdir("."):
            if f.lower().endswith(".csv") and "zone" in f.lower():
                os.rename(f, "zone.csv")
                break

    os.remove(tmp_7z)

    nomi_zone = {}
    with open("zone.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            comune = (row.get("Comune_descrizione") or "").strip().upper()
            if comune != COMUNE_TARGET:
                continue
            zona = row.get("Zona", "").strip()
            descr = row.get("Zona_Descr", "").strip()
            if zona and zona not in nomi_zone:
                nomi_zone[zona] = descr

    return nomi_zone


def main():
    download_and_extract()
    dati_garage = estrai_roma_garage()
    nomi_zone = estrai_nomi_zone()

    # Combina i due dataset
    output = {}
    for zona, dati in dati_garage.items():
        output[zona] = {
            **dati,
            "nome_zona": nomi_zone.get(zona, ""),
        }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSalvato {OUTPUT_FILE} con {len(output)} zone OMI per Roma (garage/box)")
    print("\nEsempio prime 3 zone:")
    for i, (zona, dati) in enumerate(output.items()):
        if i >= 3:
            break
        print(f"  Zona {zona} ({dati['nome_zona'][:50]}): {dati['compr_min']}-{dati['compr_max']} EUR/mq")


if __name__ == "__main__":
    main()
