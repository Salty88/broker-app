"""Offizielle Quellen und Gegenproben für BroKer.

- EZB (offizielle Schnittstelle): Euro-Referenzkurs zum US-Dollar, Leitzinsen
- Kraken (offizielle Börsen-Schnittstelle): zweite Quelle für Bitcoin und Ethereum
- tagesschau / ARD (Nachrichten-Schnittstelle): aktuelle Wirtschaftsmeldungen

Jede Funktion gibt bei einem Ausfall None oder eine leere Liste zurück, damit
ein fehlender Dienst nie den ganzen Lauf stoppt.
"""
import csv
import io
from datetime import datetime, timezone

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (BroKer)"}
EZB = "https://data-api.ecb.europa.eu/service/data"


def _ezb_letzte(reihe: str) -> tuple[str, float] | None:
    try:
        r = requests.get(f"{EZB}/{reihe}", params={"lastNObservations": 1, "format": "csvdata"}, headers=UA, timeout=20)
        r.raise_for_status()
        zeile = list(csv.DictReader(io.StringIO(r.text)))[-1]
        return zeile["TIME_PERIOD"], float(zeile["OBS_VALUE"])
    except Exception:
        return None


def ezb_eurusd() -> tuple[str, float] | None:
    """Euro-Referenzkurs der EZB: wie viele US-Dollar ein Euro kostet."""
    return _ezb_letzte("EXR/D.USD.EUR.SP00.A")


def ezb_leitzinsen() -> dict:
    """Einlagensatz und Hauptrefinanzierungssatz der EZB."""
    out = {}
    for schluessel, reihe in (("einlagensatz", "FM/D.U2.EUR.4F.KR.DFR.LEV"),
                              ("hauptrefi", "FM/D.U2.EUR.4F.KR.MRR_FR.LEV")):
        wert = _ezb_letzte(reihe)
        if wert:
            out[schluessel] = {"datum": wert[0], "wert": wert[1]}
    return out


KRAKEN_PAAR = {"BTCUSDT": "XBTUSD", "ETHUSDT": "ETHUSD"}


def kraken_schluss(ticker: str) -> pd.Series | None:
    """Tagesschlusskurse in USD von Kraken, nur abgeschlossene Tage."""
    paar = KRAKEN_PAAR.get(ticker)
    if not paar:
        return None
    try:
        r = requests.get("https://api.kraken.com/0/public/OHLC", params={"pair": paar, "interval": 1440}, headers=UA, timeout=20)
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            return None
        reihe = next(v for k, v in d["result"].items() if k != "last")
        s = pd.Series([float(x[4]) for x in reihe], index=pd.to_datetime([x[0] for x in reihe], unit="s"))
        heute = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
        return s[s.index < heute]
    except Exception:
        return None


# ---------------------------------------------------------------- Datenvertrauen

def _de(zahl: float, stellen: int = 1) -> str:
    return f"{zahl:.{stellen}f}".replace(".", ",")


def vertrauen(c: pd.Series, ticker: str, zweitquelle: pd.Series | None = None) -> dict:
    """Ampel je Wert: gruen = bestätigt, gelb = Auffälligkeit, rot = nicht verwenden."""
    gruende, stufe = [], "gruen"
    krypto = ticker.endswith("USDT")

    def melde(text, neu):
        nonlocal stufe
        gruende.append(text)
        if neu == "rot" or (neu == "gelb" and stufe == "gruen"):
            stufe = neu

    alter = (pd.Timestamp.now(tz="UTC").normalize().tz_localize(None) - c.index[-1]).days
    if alter > 10:
        melde(f"Letzter Kurs ist {alter} Tage alt.", "rot")
    elif alter > 5:
        melde(f"Letzter Kurs ist {alter} Tage alt.", "gelb")

    jahr = c[c.index >= c.index[-1] - pd.Timedelta(days=365)]
    spruenge = jahr.pct_change().abs()
    grenze = 0.35 if krypto else 0.15
    if len(spruenge) and spruenge.max() > grenze:
        tag = spruenge.idxmax()
        melde(f"Ungewöhnlicher Tagessprung von {_de(spruenge.max() * 100, 0)} % am {tag:%d.%m.%Y}. Möglicher Datenfehler.", "gelb")

    if not krypto and len(jahr) > 20:
        luecke = jahr.index.to_series().diff().dt.days.max()
        if luecke > 10:
            melde(f"Lücke von {int(luecke)} Tagen in der Kurshistorie.", "gelb")

    gegenprobe = None
    if zweitquelle is not None and len(zweitquelle):
        gemeinsam = c.index.intersection(zweitquelle.index)
        if len(gemeinsam):
            tag = gemeinsam[-1]
            abw = abs(c[tag] / zweitquelle[tag] - 1) * 100
            gegenprobe = {"datum": str(tag.date()), "abweichung_pct": round(abw, 2)}
            if abw > 5:
                melde(f"Zweite Börse (Kraken) weicht um {_de(abw)} % ab. Kurs nicht verwenden.", "rot")
            elif abw > 1.5:
                melde(f"Zweite Börse (Kraken) weicht um {_de(abw)} % ab.", "gelb")
            else:
                gruende.append(f"Von zweiter Börse (Kraken) bestätigt, Abweichung {_de(abw, 2)} %.")
    if not gruende:
        gruende.append("Keine Auffälligkeiten: aktuell, ohne Sprünge und Lücken.")
    return {"vertrauen": stufe, "vertrauen_gruende": gruende, "gegenprobe": gegenprobe}


# ---------------------------------------------------------------- Nachrichten

# Stichwörter je Thema. Treffer im Titel, Vorspann oder in den Schlagworten.
THEMEN = {
    "Krypto": ["Bitcoin", "Krypto", "Ethereum", "Blockchain", "Kryptowährung"],
    "Zinsen und Notenbanken": ["EZB", "Zins", "Leitzins", "Notenbank", "Fed", "Federal Reserve", "Lagarde", "Powell", "Inflation"],
    "Börse allgemein": ["Börse", "Aktie", "DAX", "Dax", "Wall Street", "Dow Jones", "Anleger", "Aktienmarkt", "Kurssturz", "Rekordhoch"],
    "Deutschland": ["DAX", "Dax", "deutsche Wirtschaft", "Konjunktur", "Bundesregierung", "Rezession", "ifo"],
    "USA und Technologie": ["Nasdaq", "Wall Street", "Apple", "Microsoft", "Nvidia", "Amazon", "Alphabet", "Google", "Meta", "Tesla", "KI", "Künstliche Intelligenz", "Zölle", "Trump"],
    "Europa": ["Europa", "EU-Kommission", "Euro", "Eurozone", "Euroraum"],
    "Schwellenländer": ["China", "Indien", "Schwellenländer", "Brasilien", "Taiwan"],
    "Anleihen": ["Anleihe", "Bundesanleihe", "Staatsanleihe", "Rendite", "Bund"],
    "Gold und Rohstoffe": ["Gold", "Goldpreis", "Rohstoff", "Ölpreis", "Öl"],
    "Energie": ["Solar", "Windkraft", "Erneuerbare", "Energiewende", "Strompreis"],
}


def themen_fuer(wert: dict) -> list[str]:
    """Welche Themen einen Wert betreffen, aus Name und Kategorie abgeleitet."""
    text = f"{wert.get('name', '')} {wert.get('kategorie', '')} {wert.get('rolle', '')}"
    t = []
    if wert.get("ticker", "").endswith("USDT"):
        return ["Krypto"]
    if "Gold" in text:
        return ["Gold und Rohstoffe", "Zinsen und Notenbanken"]
    if any(k in text for k in ("Bond", "Anleihe", "Govt", "Overnight", "Geldmarkt")):
        return ["Anleihen", "Zinsen und Notenbanken"]
    t += ["Börse allgemein", "Zinsen und Notenbanken"]
    if "DAX" in text or "Deutschland" in text:
        t.append("Deutschland")
    if any(k in text for k in ("S&P 500", "USA", "NASDAQ", "Nasdaq")):
        t.append("USA und Technologie")
    if "Europe" in text or "Europa" in text:
        t.append("Europa")
    if any(k in text for k in ("EM IMI", "Schwellenländer", "All Country", "All-World", "ACWI")):
        t.append("Schwellenländer")
    if any(k in text for k in ("World", "Welt")):
        t += ["USA und Technologie", "Europa"]
    if "Energy" in text or "Energie" in text:
        t.append("Energie")
    return list(dict.fromkeys(t))


def _trifft(text: str, wort: str) -> bool:
    # Kurze Wörter (EZB, KI, Öl, Fed) nur als ganzes Wort, sonst auch als Wortteil
    import re
    if len(wort) <= 4:
        return re.search(rf"(?<![\wÄÖÜäöüß]){re.escape(wort)}(?![\wÄÖÜäöüß])", text) is not None
    return wort.lower() in text.lower()


def nachrichten(werte: list[dict]) -> list[dict]:
    """Wirtschaftsmeldungen der tagesschau, den Werten über Themen zugeordnet."""
    try:
        r = requests.get("https://www.tagesschau.de/api2u/news/", params={"ressort": "wirtschaft"}, headers=UA, timeout=20)
        r.raise_for_status()
        meldungen = r.json().get("news", [])
    except Exception:
        return []
    zu_themen = {}
    for w in werte:
        for th in themen_fuer(w):
            zu_themen.setdefault(th, []).append(w["isin"])
    out = []
    for m in meldungen:
        if not m.get("title") or not m.get("shareURL"):
            continue
        text = " ".join([m.get("title", ""), m.get("topline", ""), m.get("firstSentence", ""),
                         " ".join(t.get("tag", "") for t in m.get("tags", []))])
        themen = [th for th, woerter in THEMEN.items() if any(_trifft(text, w) for w in woerter)]
        isins = sorted({i for th in themen for i in zu_themen.get(th, [])})
        out.append({
            "titel": m["title"], "dachzeile": m.get("topline", ""), "satz": m.get("firstSentence", ""),
            "datum": m.get("date", ""), "link": m["shareURL"], "themen": themen, "isins": isins,
            "quelle": "tagesschau.de",
        })
    out.sort(key=lambda x: x["datum"], reverse=True)
    return out


def jetzt() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
