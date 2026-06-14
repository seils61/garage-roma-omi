"""
Script 3: Confronto annunci garage vs valori OMI Roma

Legge:
  - annunci_garage.json  (prodotto dallo script 2)
  - omi_roma_garage.json (prodotto dallo script 1)

Per ogni annuncio con prezzo e m² disponibili:
  1. Calcola prezzo/m²
  2. Trova la zona OMI corrispondente (match testuale)
  3. Confronta col range OMI min-max
  4. Calcola lo sconto % rispetto al valore minimo OMI

Produce: report_occasioni.json
  Lista ordinata per sconto decrescente, con tutti gli annunci
  (sia sotto che sopra i valori OMI).

Logica di matching zona:
  - Cerca corrispondenza diretta tra zona dell'annuncio e nome_zona OMI
  - Se non trovata, cerca corrispondenza parziale (parole chiave)
  - Se non trovata, segna come "zona non mappata"
"""

import json
import os
import re

ANNUNCI_FILE = "annunci_garage.json"
OMI_FILE = "omi_roma_garage.json"
REPORT_FILE = "report_occasioni.json"


def normalizza(testo):
    """Normalizza testo per confronto: minuscolo, rimuove accenti comuni."""
    if not testo:
        return ""
    t = testo.lower().strip()
    sostituzioni = {
        "à": "a", "è": "e", "é": "e", "ì": "i",
        "ò": "o", "ù": "u", "-": " ", "/": " "
    }
    for orig, sost in sostituzioni.items():
        t = t.replace(orig, sost)
    return t


def parole(testo):
    """Estrae parole significative (lunghezza > 2) dal testo normalizzato."""
    return set(w for w in re.split(r'\s+', normalizza(testo)) if len(w) > 2)


def trova_zona_omi(zona_annuncio, dati_omi):
    """
    Cerca la zona OMI più compatibile con la zona dell'annuncio.
    Restituisce (codice_zona, dati_zona, tipo_match).
    """
    if not zona_annuncio:
        return None, None, "zona_mancante"

    zona_norm = normalizza(zona_annuncio)
    parole_zona = parole(zona_annuncio)

    # 1. Match esatto sul nome zona
    for codice, dati in dati_omi.items():
        nome = dati.get("nome_zona", "")
        if normalizza(nome) == zona_norm:
            return codice, dati, "esatto"

    # 2. Match parziale: la zona annuncio è contenuta nel nome OMI o viceversa
    for codice, dati in dati_omi.items():
        nome = dati.get("nome_zona", "")
        nome_norm = normalizza(nome)
        if zona_norm in nome_norm or nome_norm in zona_norm:
            return codice, dati, "parziale"

    # 3. Match per parole chiave: almeno 2 parole in comune
    migliore = None
    max_comuni = 1  # soglia minima
    for codice, dati in dati_omi.items():
        nome = dati.get("nome_zona", "")
        parole_omi = parole(nome)
        comuni = len(parole_zona & parole_omi)
        if comuni > max_comuni:
            max_comuni = comuni
            migliore = (codice, dati, "keyword")

    if migliore:
        return migliore

    return None, None, "non_mappata"


def calcola_sconto(prezzo_mq, omi_min):
    """
    Calcola lo sconto % rispetto al valore minimo OMI.
    Positivo = sotto mercato (occasione), negativo = sopra mercato.
    """
    if not omi_min or omi_min == 0:
        return None
    return round((omi_min - prezzo_mq) / omi_min * 100, 1)


def main():
    # Carica dati
    if not os.path.exists(ANNUNCI_FILE):
        print(f"File non trovato: {ANNUNCI_FILE}")
        return
    if not os.path.exists(OMI_FILE):
        print(f"File non trovato: {OMI_FILE}")
        return

    with open(ANNUNCI_FILE, "r", encoding="utf-8") as f:
        annunci = json.load(f)

    with open(OMI_FILE, "r", encoding="utf-8") as f:
        dati_omi = json.load(f)

    print(f"Annunci caricati: {len(annunci)}")
    print(f"Zone OMI caricate: {len(dati_omi)}")

    report = []

    for annuncio in annunci:
        prezzo = annuncio.get("prezzo")
        mq = annuncio.get("superficie_mq")
        zona = annuncio.get("zona", "")
        titolo = annuncio.get("titolo", "")
        link = annuncio.get("link", "")
        portale = annuncio.get("portale", "")
        data_email = annuncio.get("data_email", "")

        # Calcola prezzo/m² solo se entrambi disponibili
        prezzo_mq = None
        if prezzo and mq and mq > 0:
            prezzo_mq = round(prezzo / mq, 0)

        # Trova zona OMI corrispondente
        codice_zona, dati_zona, tipo_match = trova_zona_omi(zona, dati_omi)

        omi_min = None
        omi_max = None
        nome_zona_omi = None
        sconto_pct = None
        valutazione = "dati_insufficienti"

        if dati_zona:
            omi_min = dati_zona.get("compr_min")
            omi_max = dati_zona.get("compr_max")
            nome_zona_omi = dati_zona.get("nome_zona", codice_zona)

        if prezzo_mq and omi_min and omi_max:
            sconto_pct = calcola_sconto(prezzo_mq, omi_min)
            if prezzo_mq < omi_min:
                valutazione = "sotto_mercato"
            elif prezzo_mq <= omi_max:
                valutazione = "in_linea"
            else:
                valutazione = "sopra_mercato"
        elif not prezzo_mq:
            valutazione = "prezzo_mq_mancante"
        elif not dati_zona:
            valutazione = "zona_non_mappata"

        voce = {
            "titolo": titolo,
            "zona_annuncio": zona,
            "zona_omi": nome_zona_omi,
            "tipo_match_zona": tipo_match,
            "portale": portale,
            "prezzo": prezzo,
            "superficie_mq": mq,
            "prezzo_mq": prezzo_mq,
            "omi_min_mq": omi_min,
            "omi_max_mq": omi_max,
            "sconto_pct": sconto_pct,
            "valutazione": valutazione,
            "link": link,
            "data_email": data_email,
        }
        report.append(voce)
        print(f"  {titolo[:50]:50} | {prezzo_mq or '?':>6} €/m² | OMI {omi_min}-{omi_max} | {valutazione}")

    # Ordina: prima le occasioni (sconto maggiore), poi in_linea, poi sopra_mercato, poi mancanti
    def ordine(v):
        s = v.get("sconto_pct")
        val = v.get("valutazione")
        if s is not None:
            return (0, -s)
        if val == "zona_non_mappata":
            return (1, 0)
        return (2, 0)

    report.sort(key=ordine)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Stampa riepilogo
    sotto = [r for r in report if r["valutazione"] == "sotto_mercato"]
    in_linea = [r for r in report if r["valutazione"] == "in_linea"]
    sopra = [r for r in report if r["valutazione"] == "sopra_mercato"]
    mancanti = [r for r in report if r["valutazione"] in ("prezzo_mq_mancante", "zona_non_mappata", "dati_insufficienti")]

    print(f"\n{'='*60}")
    print(f"REPORT OCCASIONI GARAGE ROMA")
    print(f"{'='*60}")
    print(f"Sotto mercato (potenziali occasioni): {len(sotto)}")
    print(f"In linea con OMI:                     {len(in_linea)}")
    print(f"Sopra mercato:                        {len(sopra)}")
    print(f"Dati insufficienti:                   {len(mancanti)}")
    print(f"\nSalvato: {REPORT_FILE}")

    if sotto:
        print(f"\nOCCASIONI RILEVATE:")
        for r in sotto:
            print(f"  ⭐ {r['titolo'][:60]}")
            print(f"     {r['prezzo']} € | {r['superficie_mq']} m² | {r['prezzo_mq']} €/m²")
            print(f"     OMI zona {r['zona_omi']}: {r['omi_min_mq']}-{r['omi_max_mq']} €/m²")
            print(f"     Sconto vs OMI min: {r['sconto_pct']}%")
            print(f"     {r['link']}")


if __name__ == "__main__":
    main()
