"""
Script 2: Lettura notifiche annunci garage da Gmail (IMAP)

Si collega alla casella Gmail tramite IMAP, legge le email di notifica
ricevute da Immobiliare.it e Idealista per garage/box in vendita a Roma,
estrae i dati principali di ogni annuncio e li salva in annunci_garage.json.

Credenziali da GitHub Secrets:
  - OUTLOOK_EMAIL        (contiene l'indirizzo Gmail)
  - OUTLOOK_APP_PASSWORD (contiene la password per l'app Gmail)

Output: annunci_garage.json
"""

import email
import imaplib
import json
import os
import re
from email.header import decode_header
from html.parser import HTMLParser

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
OUTPUT_FILE = "annunci_garage.json"

MITTENTI_PORTALI = {
    "noreply@notifiche.immobiliare.it": "immobiliare",
    "nonrispondere@idealista.it": "idealista",
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
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
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


def pulisci_html(html):
    """Rimuove i tag HTML e restituisce il testo pulito."""
    class MLStripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.reset()
            self.fed = []
        def handle_data(self, d):
            self.fed.append(d)
        def get_data(self):
            return " ".join(self.fed)

    s = MLStripper()
    s.feed(html)
    return s.get_data()


def estrai_prezzo(testo):
    """Estrae il primo prezzo in euro trovato nel testo (es. '25.000 €' -> 25000)."""
    match = re.search(r'(\d{1,3}(?:[.,]\d{3})*)\s*[€Ee]', testo)
    if match:
        prezzo_str = match.group(1).replace(".", "").replace(",", "")
        try:
            return int(prezzo_str)
        except ValueError:
            return None
    return None


def estrai_mq(testo):
    """Estrae i m² dal testo (es. '15 m²' -> 15)."""
    match = re.search(r'(\d+)\s*m[²2]', testo)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def estrai_zona_da_titolo(titolo):
    """
    Estrae la zona/quartiere dal titolo dell'annuncio.
    Formato tipico: 'Garage in Via X, QUARTIERE, Roma'
    """
    match = re.search(r',\s*([^,]+),\s*Roma', titolo, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


# -----------------------------------------------------------------------
# PARSER IMMOBILIARE.IT
# Formato email: un annuncio per email con titolo, zona, prezzo, m²
# -----------------------------------------------------------------------

def parse_email_immobiliare(html_body, data_email):
    annunci = []

    # Estrai tutti i link agli annunci
    links = re.findall(
        r'href="(https://www\.immobiliare\.it/annunci/\d+[^"]*)"',
        html_body
    )
    # Rimuovi duplicati mantenendo l'ordine
    links_unici = list(dict.fromkeys(links))

    # Estrai titoli (testo dei link agli annunci)
    titoli = re.findall(
        r'href="https://www\.immobiliare\.it/annunci/\d+[^"]*"[^>]*>\s*([^<]+)',
        html_body
    )

    # Testo pulito per estrarre prezzo e m²
    testo = pulisci_html(html_body)

    prezzo = estrai_prezzo(testo)
    mq = estrai_mq(testo)

    # Zona: cerca pattern "zona" nell'HTML oppure estrai dal titolo
    zona = ""
    zona_match = re.search(r'<[^>]*class="[^"]*zona[^"]*"[^>]*>\s*([^<]+)', html_body, re.IGNORECASE)
    if zona_match:
        zona = zona_match.group(1).strip()

    titolo = titoli[0].strip() if titoli else ""
    if not zona and titolo:
        zona = estrai_zona_da_titolo(titolo)

    link = links_unici[0] if links_unici else ""

    if link:
        annunci.append({
            "titolo": titolo,
            "prezzo": prezzo,
            "superficie_mq": mq,
            "zona": zona,
            "link": link,
            "data_email": data_email,
        })

    return annunci


# -----------------------------------------------------------------------
# PARSER IDEALISTA
# Formato email: più annunci per email, ognuno con titolo, prezzo, descrizione
# I m² non sempre presenti nell'email — estratti dal titolo se possibile
# -----------------------------------------------------------------------

def parse_email_idealista(html_body, data_email):
    annunci = []

    # Estrai blocchi annuncio: ogni annuncio ha un link idealista.it/immobile/
    links = re.findall(
        r'href="(https://www\.idealista\.it/immobile/\d+[^"]*)"',
        html_body
    )
    links_unici = list(dict.fromkeys(links))

    # Per ogni link, cerca il titolo e prezzo nelle vicinanze nell'HTML
    # Strategia: spezziamo l'HTML in blocchi attorno ai link
    blocchi = re.split(r'https://www\.idealista\.it/immobile/\d+', html_body)

    for i, link in enumerate(links_unici):
        # Prendi il testo del blocco precedente + successivo per estrarre i dati
        blocco = ""
        if i < len(blocchi) - 1:
            blocco = blocchi[i] + blocchi[i + 1]
        elif i < len(blocchi):
            blocco = blocchi[i]

        testo_blocco = pulisci_html(blocco)

        # Estrai titolo dal link stesso o dal testo vicino
        titolo_match = re.search(
            r'href="' + re.escape(link) + r'"[^>]*>\s*([^<]{10,100})',
            html_body
        )
        titolo = titolo_match.group(1).strip() if titolo_match else ""

        prezzo = estrai_prezzo(testo_blocco)
        mq = estrai_mq(testo_blocco) or estrai_mq(titolo)
        zona = estrai_zona_da_titolo(titolo)

        if link:
            annunci.append({
                "titolo": titolo,
                "prezzo": prezzo,
                "superficie_mq": mq,
                "zona": zona,
                "link": link,
                "data_email": data_email,
            })

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

    # Legge tutte le email non lette
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
            print(f"  - Mittente non riconosciuto: {mittente} — saltato")
            continue

        html_body = estrai_corpo_html(msg)
        parser = PARSER_PER_PORTALE[portale]
        annunci = parser(html_body, data_email)

        for a in annunci:
            a["portale"] = portale
            a["oggetto_email"] = oggetto
            tutti_annunci.append(a)

        print(f"  - [{portale}] '{oggetto}': {len(annunci)} annunci estratti")

        # Segna come letta dopo averla processata con successo
        imap.store(msg_id, '+FLAGS', '\\Seen')

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
