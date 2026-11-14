"""Erzeugt die Daten für die BroKer-App.

    python broker/daten.py app/data   # schreibt werte.json und verlauf.json

werte.json:   eine Zeile je Wert mit Signal, Entwicklung (Tag, Monat, Quartal,
              seit Jahresbeginn, 12 Monate) und Test der Regel gegen Halten.
verlauf.json: Schlusskurs und 200-Tage-Linie der letzten 12 Monate je Wert.

Gruppen: "Watchlist" = deine Werte aus watchlist.json,
         "Baustein"  = Beispiel-ETFs zur Orientierung (keine Empfehlung).
Jede Datei trägt ihren eigenen Code in "meta", damit jede Zahl nachprüfbar ist.
"""
import json
from pathlib import Path

import pandas as pd

import broker  # noqa: E402



# Beispiel-Bausteine für eine breite Verteilung (ISIN geprüft, keine Empfehlung).
BAUSTEINE = [
    {"isin": "IE00B3RBWM25", "ticker": "VGWL.DE", "rolle": "Welt-Aktien, ein ETF für alles (ausschüttend)"},
    {"isin": "IE00BK5BQT80", "ticker": "VWCE.DE", "rolle": "Welt-Aktien, ein ETF für alles (thesaurierend)"},
    {"isin": "IE00B4L5Y983", "ticker": "EUNL.DE", "rolle": "Aktien Industrieländer (ca. 70 %)"},
    {"isin": "IE00BKM4GZ66", "ticker": "IS3N.DE", "rolle": "Aktien Schwellenländer (ca. 30 %)"},
    {"isin": "LU0290358497", "ticker": "XEON.DE", "rolle": "Sicherheitsbaustein Geldmarkt"},
]


def veraenderung(c: pd.Series, tage: int) -> float | None:
    """Prozentuale Änderung gegenüber dem letzten Schlusskurs vor `tage` Kalendertagen."""
    stichtag = c.index[-1] - pd.Timedelta(days=tage)
    vorher = c[c.index <= stichtag]
    return None if vorher.empty else round(float(c.iloc[-1] / vorher.iloc[-1] - 1) * 100, 2)


def seit_jahresbeginn(c: pd.Series) -> float | None:
    vorjahr = c[c.index < pd.Timestamp(year=c.index[-1].year, month=1, day=1)]
    return None if vorjahr.empty else round(float(c.iloc[-1] / vorjahr.iloc[-1] - 1) * 100, 2)


def zeile(w: dict, gruppe: str, rolle: str = "") -> tuple[dict, list[dict]]:
    lage = broker.lage(w)
    c = broker.kurse(w["ticker"])
    sma = c.rolling(200).mean()
    t = lage["test"]
    row = {
        "isin": w["isin"], "name": w["name"], "gruppe": gruppe, "rolle": rolle,
        "boerse": w.get("boerse"), "ticker": w["ticker"], "waehrung": w.get("waehrung"),
        "datum": lage["datum"], "kurs": lage["kurs"], "sma200": lage["sma200"],
        "signal": lage["signal"], "neu": lage["neu"], "abstand_pct": lage["abstand_pct"],
        "rsi14": lage["rsi14"], "signal_seit": lage["signal_seit"], "tage_seit": lage["tage_seit"],
        "monat_pct": veraenderung(c, 30), "quartal_pct": veraenderung(c, 91),
        "ytd_pct": seit_jahresbeginn(c), "jahr_pct": veraenderung(c, 365),
        "test_seit": t["seit"], "regel_pa": t["regel_pa"], "halten_pa": t["halten_pa"],
        "regel_dd": t["regel_dd"], "halten_dd": t["halten_dd"],
    }
    # Tagesänderung: gegenüber dem vorherigen Handelstag
    row["tag_pct"] = round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2)
    jahr = c.index[-1] - pd.Timedelta(days=365)
    verlauf = [{"isin": w["isin"], "datum": str(d.date()), "kurs": round(float(k), 4),
                "sma200": None if pd.isna(s) else round(float(s), 4)}
               for d, k, s in zip(c.index, c, sma) if d >= jahr]
    return row, verlauf


def eurusd() -> float:
    """Letzter Schlusskurs EUR/USD (wie viele Dollar ein Euro kostet)."""
    return float(broker.kurse("EURUSD=X").iloc[-1])


def fondsart(isin: str, name: str, ticker: str) -> str:
    """Grobe Einordnung für die Steuerschätzung (Teilfreistellung)."""
    if ticker.endswith("USDT"):
        return "Krypto"
    if any(k in name for k in ("Overnight", "Money Market", "Geldmarkt")):
        return "Sonstiger Fonds"
    if "ETF" in name or "UCITS" in name:
        return "Aktien-ETF"
    return "Aktie"


def main(out: str) -> None:
    OUT = Path(out)
    OUT.mkdir(parents=True, exist_ok=True)
    zeilen, verlauf = [], []
    try:
        fx = eurusd()
    except Exception:
        fx = None
    eintraege = [(w, "Watchlist", "") for w in broker.lade_liste()]
    beobachtet = {w["isin"] for w in broker.lade_liste()}
    for b in BAUSTEINE:
        if b["isin"] not in beobachtet:
            m = broker.meta(b["ticker"]) or {}
            w = {"isin": b["isin"], "ticker": b["ticker"], "name": m.get("longName") or b["isin"],
                 "waehrung": m.get("currency"), "boerse": m.get("fullExchangeName")}
            eintraege.append((w, "Baustein", b["rolle"]))
    for w, gruppe, rolle in eintraege:
        try:
            r, v = zeile(w, gruppe, rolle)
            r["fondsart"] = fondsart(r["isin"], r["name"], r["ticker"])
            if r.get("waehrung") == "EUR":
                r["kurs_eur"] = r["kurs"]
            elif r.get("waehrung") == "USD" and fx:
                r["kurs_eur"] = round(r["kurs"] / fx, 2)
            zeilen.append(r)
            verlauf += v
        except Exception as err:
            zeilen.append({"isin": w["isin"], "name": w.get("name", w["isin"]), "gruppe": gruppe,
                           "rolle": rolle, "fehler": f"{type(err).__name__}: {err}"})

    code = [
        {"label": "Kursquellen", "value": "Yahoo Finance (Aktien, ETFs), Binance (Krypto); nur abgeschlossene Tageskerzen"},
        {"label": "Erzeugt", "value": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")},
        {"label": "EURUSD", "value": "" if fx is None else f"{fx:.4f}"},
    ]
    (OUT / "werte.json").write_text(json.dumps({"rows": zeilen, "meta": code}, ensure_ascii=False))
    (OUT / "verlauf.json").write_text(json.dumps({"rows": verlauf, "meta": code}, ensure_ascii=False))
    print(f"{len(zeilen)} Werte, {len(verlauf)} Verlaufspunkte -> {OUT}")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "app/data")
