"""
Script 2: Lettura notifiche annunci garage da Gmail (IMAP)
"""

import email
import imaplib
import json
import os
import re
import urllib.request
import urllib.error
from email.header import decode_header
from html.parser import HTMLParser

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
OUTPUT_FILE = "annunci_garage.json"

MITTENTI_PORTALI = {
    "noreply@notifiche.immobiliare.it": "immobiliare",
    "nonrispondere@idealista.it": "idealista",
}

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
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
    patterns = [
        r'(\d{1,3}(?:\.\d{3})+)\s*€',
        r'€\s*(\d{1,3}(?:\.\d{3})+)',
        r'(\d{1,3}(?:\.\d{3})+)\s*[Ee]uro',
    ]
    for pattern in patterns:
        match = re.search(pattern, testo)
        if match:
            prezzo_str = match.group(1).replace(".", "")
            try:
                return int(prezzo_str)
            except ValueError:
                continue
    return None


def estrai_mq(testo):
    match = re.search(r'(\d+)\s*m[²2]', testo)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def estrai_zona_da_titolo(titolo):
    match = re.search(r',\s*([^,]+),\s*Roma', titolo, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def scarica_pagina(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS_HTTP)
        with urllib.request.urlopen(req, timeout=10) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="ignore"), response.geturl()
    except Exception as e:
        print(f"    Errore scaricando {url}: {e}")
        return "", url


def segui_redirect(url):
    """Segue un link di tracking e restituisce l'URL finale reale."""
    try:
        req = urllib.request.Request(url, headers=HEADERS_HTTP)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.geturl()
    except Exception as e:
        print(f"    Errore seguendo redirect {url}: {e}")
        return url


def arricchisci_da_pagina_immobiliare(url):
    """Scarica la pagina annuncio di Immobiliare.it ed estrae prezzo e m²."""
    html, url_finale = scarica_pagina(url)
    if not html:
        return None, None, url_finale

    testo = pulisci_html(html)
    prezzo = estrai_prezzo(testo)
    mq = estrai_mq(testo)
    return prezzo, mq, url_finale


def parse_email_immobiliare(html_body, data_email):
    annunci = []

    # Estrai testo pulito dall'email
    testo = pulisci_html(html_body)

    # Prezzo e m² dal testo email (funzionava già)
    prezzo = estrai_prezzo(testo)
    mq = estrai_mq(testo)

    # Titolo: cerca "Garage..." o "Box..." nel testo
    titolo = ""
    titolo_match = re.search(
        r'((?:Garage|Box|Posto auto)[^€\n]{5,100})',
        testo, re.IGNORECASE
    )
    if titolo_match:
        titolo = " ".join(titolo_match.group(1).split()).strip()

    # Zona: cerca il quartiere nel titolo estratto
    zona = estrai_zona_da_titolo(titolo)

    # Se zona vuota, cerca pattern "Quartiere, Roma" nel testo
    if not zona:
        zona_match = re.search(
            r'([A-ZÀÈÌÒÙ][a-zàèìòù]+(?:\s+[A-ZÀÈÌÒÙ][a-zàèìòù]+)*),\s*Roma',
            testo
        )
        if zona_match:
            zona = zona_match.group(1).strip()

    # Link: prendi il primo link di tracking come riferimento
    # (non seguiamo il redirect — usiamo direttamente immobiliare.it)
    link = ""
    # Cerca ID annuncio nel testo o nei link
    id_match = re.search(r'/annunci/(\d+)', html_body)
    if id_match:
        link = f"https://www.immobiliare.it/annunci/{id_match.group(1)}/"
    else:
        # Fallback: primo link di tracking
        tracking = re.findall(
            r'href="(https://clicks\.immobiliare\.it/f/a/[^"]+)"',
            html_body
        )
        link = tracking[1] if len(tracking) > 1 else (tracking[0] if tracking else "")

    print(f"    Immobiliare: '{titolo}' | {prezzo} € | {mq} m² | {zona}")

    if prezzo and link:
        annunci.append({
            "titolo": titolo,
            "prezzo": prezzo,
            "superficie_mq": mq,
            "zona": zona,
            "link": link,
            "data_email": data_email,
        })

    return annunci




def parse_email_idealista(html_body, data_email):
    annunci = []
    id_visti = set()

    ids_immobile = re.findall(r'/immobile/(\d+)/', html_body)
    ids_unici = list(dict.fromkeys(ids_immobile))

    for id_immobile in ids_unici:
        if id_immobile in id_visti:
            continue
        id_visti.add(id_immobile)

        pos = html_body.find(f'/immobile/{id_immobile}/')
        if pos == -1:
            continue
        blocco = html_body[max(0, pos-200):pos+1500]
        testo_blocco = pulisci_html(blocco)

        titolo_match = re.search(
            r'href="https://www\.idealista\.it/immobile/' + id_immobile +
            r'/[^"]*utm_link=propertyNewLink[^"]*"[^>]*>\s*([^<]{10,150})',
            html_body
        )
        titolo = titolo_match.group(1).strip() if titolo_match else ""

        if not titolo:
            titolo_match2 = re.search(
                r'href="https://www\.idealista\.it/immobile/' + id_immobile +
                r'/[^"]*"[^>]*>\s*([A-Z][^<]{10,150})',
                html_body
            )
            titolo = titolo_match2.group(1).strip() if titolo_match2 else ""

        prezzo = estrai_prezzo(testo_blocco)
        mq = estrai_mq(testo_blocco) or estrai_mq(titolo)
        zona = estrai_zona_da_titolo(titolo)
        link_pulito = f"https://www.idealista.it/immobile/{id_immobile}/"

        annunci.append({
            "titolo": titolo,
            "prezzo": prezzo,
            "superficie_mq": mq,
            "zona": zona,
            "link": link_pulito,
            "data_email": data_email,
        })

    return annunci


PARSER_PER_PORTALE = {
    "immobiliare": parse_email_immobiliare,
    "idealista": parse_email_idealista,
}


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

