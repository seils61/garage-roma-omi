"""
Script 2: Lettura notifiche annunci garage da Outlook (IMAP)

Si collega alla casella Outlook tramite IMAP, legge le email di notifica
ricevute dai portali immobiliari (Immobiliare.it, Idealista, ecc.) per
"garage/box in vendita a Roma", estrae i dati principali di ogni annuncio
(prezzo, superficie, zona, link) e li salva in un file JSON.

Credenziali lette da variabili d'ambiente (impostate come Secrets su
GitHub Actions):
  - OUTLOOK_EMAIL
  - OUTLOOK_APP_PASSWORD

Output: annunci_garage.json
  Lista di oggetti: {portale, titolo, prezzo, superficie_mq, zona, link, data_email}

NOTA: le funzioni di parsing (parse_email_immobiliare, parse_email_idealista)
sono placeholder e vanno completate con il formato reale delle email,
che varia da portale a portale.
"""

import email
import imaplib
import json
import os
import re
from email.header import decode_header

IMAP_SERVER = "imap.gmail.com"
"
IMAP_PORT = 993

OUTPUT_FILE = "annunci_garage.json"

# Mappa: indirizzo mittente -> nome portale
# Da completare/verificare con gli indirizzi reali dei mittenti delle notifiche
MITTENTI_PORTALI = {
    "noreply@immobiliare.it": "immobiliare",
    "alert@idealista.it": "idealista",
    # aggiungere altri mittenti man mano che li individuiamo
}


def connetti_imap():
    email_addr = os.environ["OUTLOOK_EMAIL"]
    app_password = os.environ["OUTLOOK_APP_PASSWORD"]

    imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    imap.login(email_addr, app_password)
    return imap


def decodifica_header(raw):
    if raw is None:
        return ""
    parti = decode_header(raw)
    risultato = ""
    for testo, encoding in parti:
        if isinstance(testo, bytes):
            risultato += testo.decode(encoding or "utf-8", errors="ignore")
        else:
            risultato += testo
    return risultato


def estrai_corpo_html(msg):
    """Estrae il corpo HTML (o testo) di un messaggio email."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="ignore")
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="ignore")
    return ""


# -----------------------------------------------------------------------
# FUNZIONI DI PARSING SPECIFICHE PER PORTALE
# Da completare con il formato reale delle email (esempi necessari)
# -----------------------------------------------------------------------

def parse_email_immobiliare(html_body, data_email):
    """
    TODO: completare con il formato reale dell'email di Immobiliare.it.
    Deve estrarre uno o più annunci dal corpo HTML e restituire una lista
    di dict con: titolo, prezzo, superficie_mq, zona, link
    """
    annunci = []
    return annunci


def parse_email_idealista(html_body, data_email):
    """
    TODO: completare con il formato reale dell'email di Idealista.
    Deve estrarre uno o più annunci dal corpo HTML e restituire una lista
    di dict con: titolo, prezzo, superficie_mq, zona, link
    """
    annunci = []
    return annunci


PARSER_PER_PORTALE = {
    "immobiliare": parse_email_immobiliare,
    "idealista": parse_email_idealista,
}


# -----------------------------------------------------------------------
# LOGICA PRINCIPALE
# -----------------------------------------------------------------------

def identifica_portale(mittente):
    mittente_lower = mittente.lower()
    for indirizzo, portale in MITTENTI_PORTALI.items():
        if indirizzo.lower() in mittente_lower:
            return portale
    return None


def leggi_notifiche():
    imap = connetti_imap()
    imap.select("INBOX")

    status, messaggi = imap.search(None, "UNSEEN")
    ids = messaggi[0].split()

    print(f"Trovate {len(ids)} email non lette")

    tutti_annunci = []

    for msg_id in ids:
        status, dati = imap.fetch(msg_id, "(RFC822)")
        raw_email = dati[0][1]
        msg = email.message_from_bytes(raw_email)

        mittente = decodifica_header(msg.get("From"))
        oggetto = decodifica_header(msg.get("Subject"))
        data_email = decodifica_header(msg.get("Date"))

        portale = identifica_portale(mittente)
        if portale is None:
            continue

        html_body = estrai_corpo_html(msg)
        parser = PARSER_PER_PORTALE[portale]
        annunci = parser(html_body, data_email)

        for a in annunci:
            a["portale"] = portale
            a["oggetto_email"] = oggetto
            tutti_annunci.append(a)

        print(f"  - [{portale}] '{oggetto}': {len(annunci)} annunci estratti")

        # imap.store(msg_id, '+FLAGS', '\\Seen')

    imap.logout()
    return tutti_annunci


def main():
    nuovi_annunci = leggi_notifiche()

    esistenti = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            esistenti = json.load(f)

    link_esistenti = {a.get("link") for a in esistenti if a.get("link")}
    aggiunti = 0
    for a in nuovi_annunci:
        if a.get("link") and a["link"] not in link_esistenti:
            esistenti.append(a)
            link_esistenti.add(a["link"])
            aggiunti += 1

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(esistenti, f, ensure_ascii=False, indent=2)

    print(f"\nAggiunti {aggiunti} nuovi annunci. Totale: {len(esistenti)}")


if __name__ == "__main__":
    main()
