"""BroKer: beobachtet deine Werte per ISIN und meldet den Stand der Regel
"investiert, solange der Kurs über dem 200-Tage-Durchschnitt liegt".

    python broker.py liste                      # beobachtete Werte
    python broker.py hinzufuegen IE00B5BMR087   # Wert per ISIN aufnehmen
    python broker.py hinzufuegen BTC            # Krypto: BTC oder ETH
    python broker.py hinzufuegen <ISIN> --ticker SXR8.DE   # Börsenplatz selbst wählen
    python broker.py entfernen IE00B5BMR087
    python broker.py signale [--json]           # aktueller Signalstand

Die Datei ist bewusst eigenständig (nur pandas und requests), damit sie auch
auch allein in GitHub Actions läuft.
Nur Regelstand, keine Anlageberatung.
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

LISTE = Path(__file__).resolve().parent.parent / "watchlist.json"
UA = {"User-Agent": "Mozilla/5.0"}
YAHOO = "https://query2.finance.yahoo.com"
KRYPTO = {"BTC": ("BTCUSDT", "Bitcoin"), "ETH": ("ETHUSDT", "Ethereum")}
# Bevorzugte Börsenplätze mit Euro-Kurs: Xetra, Frankfurt, dann andere.
SUFFIXE = ["DE", "F", "MI", "AS", "PA", "SG", "MU", "DU"]


# ---------------------------------------------------------------- Daten

def kurse(ticker: str) -> pd.Series:
    """Schlusskurse nur abgeschlossener Tage (laufender Tag wird verworfen)."""
    if ticker.endswith("USDT"):
        rows, start = [], 0
        while True:
            r = requests.get("https://data-api.binance.vision/api/v3/klines",
                             params={"symbol": ticker, "interval": "1d", "startTime": start, "limit": 1000}, timeout=30)
            r.raise_for_status()
            batch = r.json()
            rows += batch
            if len(batch) < 1000:
                break
            start = batch[-1][0] + 86_400_000
        c = pd.Series([float(x[4]) for x in rows], index=pd.to_datetime([x[0] for x in rows], unit="ms"))
    else:
        r = requests.get(f"{YAHOO}/v8/finance/chart/{ticker}",
                         params={"period1": 0, "period2": int(time.time()), "interval": "1d"}, headers=UA, timeout=30)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
        c = pd.Series(adj or res["indicators"]["quote"][0]["close"],
                      index=pd.to_datetime(res["timestamp"], unit="s").normalize()).dropna()
    heute = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    c = c[c.index < heute]
    return c[~c.index.duplicated(keep="last")]


def meta(ticker: str) -> dict | None:
    r = requests.get(f"{YAHOO}/v8/finance/chart/{ticker}", params={"range": "5d", "interval": "1d"}, headers=UA, timeout=15)
    if r.status_code != 200:
        return None
    res = r.json()["chart"]["result"]
    if not res or not res[0].get("indicators", {}).get("quote", [{}])[0].get("close"):
        return None  # Börsenplatz ohne Kursdaten
    return res[0]["meta"]


def finde(isin: str) -> dict:
    """Sucht zur ISIN einen Börsenplatz, möglichst mit Euro-Kurs."""
    r = requests.get(f"{YAHOO}/v1/finance/search",
                     params={"q": isin, "quotesCount": 10, "newsCount": 0, "region": "DE", "lang": "de-DE"},
                     headers=UA, timeout=15)
    r.raise_for_status()
    treffer = [q for q in r.json().get("quotes", []) if q.get("symbol")]
    if not treffer:
        raise ValueError(f"Keine Kursdaten zur ISIN {isin} gefunden. Tipp: --ticker selbst angeben.")
    kandidaten = []
    for q in treffer:
        basis = q["symbol"].split(".")[0]
        kandidaten += [f"{basis}.{s}" for s in SUFFIXE] + [q["symbol"]]
    gesehen, ersatz = set(), None
    for t in kandidaten:
        if t in gesehen:
            continue
        gesehen.add(t)
        m = meta(t)
        if not m:
            continue
        info = {"ticker": t, "name": m.get("longName") or m.get("shortName") or t,
                "waehrung": m.get("currency"), "boerse": m.get("fullExchangeName")}
        if info["waehrung"] == "EUR":
            return info
        ersatz = ersatz or info
    if ersatz:
        return ersatz
    raise ValueError(f"Kein handelbarer Börsenplatz zur ISIN {isin} gefunden.")


# ---------------------------------------------------------------- Liste

def lade_liste() -> list[dict]:
    return json.loads(LISTE.read_text())["werte"] if LISTE.exists() else []


def speichere(werte: list[dict]) -> None:
    LISTE.write_text(json.dumps({"werte": werte}, ensure_ascii=False, indent=2) + "\n")


def hinzufuegen(kennung: str, ticker: str | None = None) -> dict:
    kennung = kennung.strip().upper()
    werte = lade_liste()
    if any(w["isin"] == kennung for w in werte):
        raise ValueError(f"{kennung} wird schon beobachtet.")
    if kennung in KRYPTO:
        t, name = KRYPTO[kennung]
        eintrag = {"isin": kennung, "name": name, "ticker": t, "waehrung": "USD", "boerse": "Binance (Kurs in USD)"}
    else:
        if len(kennung) != 12 or not kennung[:2].isalpha():
            raise ValueError("Eine ISIN hat 12 Zeichen und beginnt mit zwei Buchstaben, z. B. IE00B5BMR087.")
        if ticker:
            m = meta(ticker) or {}
            eintrag = {"isin": kennung, "name": m.get("longName") or ticker, "ticker": ticker,
                       "waehrung": m.get("currency"), "boerse": m.get("fullExchangeName")}
        else:
            eintrag = {"isin": kennung, **finde(kennung)}
    werte.append(eintrag)
    speichere(werte)
    return eintrag


def entfernen(kennung: str) -> None:
    kennung = kennung.strip().upper()
    werte = lade_liste()
    rest = [w for w in werte if w["isin"] != kennung]
    if len(rest) == len(werte):
        raise ValueError(f"{kennung} steht nicht auf der Liste.")
    speichere(rest)


# ---------------------------------------------------------------- Signale

def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def testbefund(c: pd.Series, sig: pd.Series, tage_pro_jahr: int) -> dict:
    """Regel gegen Halten über die ganze verfügbare Historie (0,1 % Gebühr je Wechsel)."""
    ret = c.pct_change().fillna(0)
    pos = sig.shift(1).fillna(0)
    regel = (1 + pos * ret - pos.diff().abs().fillna(0) * 0.001).cumprod()
    halten = (1 + ret).cumprod()
    jahre = len(c) / tage_pro_jahr

    def pa(eq):
        return round((eq.iloc[-1] ** (1 / jahre) - 1) * 100, 1)

    def dd(eq):
        return round((eq / eq.cummax() - 1).min() * 100, 1)

    return {"seit": str(c.index[200].date()), "regel_pa": pa(regel), "halten_pa": pa(halten),
            "regel_dd": dd(regel), "halten_dd": dd(halten)}


def lage(w: dict) -> dict:
    c = kurse(w["ticker"])
    if len(c) < 260:
        raise ValueError("Zu wenig Kurshistorie (unter einem Jahr) für die 200-Tage-Regel.")
    sma = c.rolling(200).mean()
    sig = (c > sma).astype(int)
    sig.iloc[:200] = 0
    wechsel = sig[sig.diff().fillna(0) != 0]
    seit = wechsel.index[-1] if len(wechsel) else sig.index[0]
    tpj = 365 if w["ticker"].endswith("USDT") else 252
    return {**w,
            "datum": str(c.index[-1].date()), "kurs": round(float(c.iloc[-1]), 2),
            "sma200": round(float(sma.iloc[-1]), 2),
            "abstand_pct": round(float(c.iloc[-1] / sma.iloc[-1] - 1) * 100, 1),
            "rsi14": round(float(rsi(c).iloc[-1]), 1),
            "signal": "investiert" if sig.iloc[-1] else "Cash",
            "signal_seit": str(seit.date()), "tage_seit": int((c.index[-1] - seit).days),
            "neu": bool(sig.iloc[-1] != sig.iloc[-2]),
            "test": testbefund(c.iloc[-min(len(c), 15 * tpj):], sig.iloc[-min(len(c), 15 * tpj):], tpj)}


def signale() -> list[dict]:
    out = []
    for w in lade_liste():
        try:
            out.append(lage(w))
        except Exception as err:  # ein Wert ohne Daten soll die anderen nicht stoppen
            out.append({**w, "fehler": f"{type(err).__name__}: {err}"})
    return out


def text(werte: list[dict]) -> str:
    if not werte:
        return "BroKer beobachtet noch nichts. Füge Werte hinzu: python broker.py hinzufuegen <ISIN>"
    zeilen = ["Regel: investiert, solange der Kurs über dem 200-Tage-Durchschnitt liegt", ""]
    for w in sorted(werte, key=lambda x: not x.get("neu", False)):
        zeilen.append(f"{w['name']}  (ISIN {w['isin']})")
        if "fehler" in w:
            zeilen += [f"  keine Daten: {w['fehler']}", ""]
            continue
        neu = "  << NEUES SIGNAL" if w["neu"] else ""
        knapp = "  (knapp an der Linie, Fehlsignal möglich)" if abs(w["abstand_pct"]) < 1 else ""
        t = w["test"]
        zeilen += [
            f"  {w['signal'].upper()}{neu}{knapp}",
            f"  Kurs {w['kurs']} {w['waehrung']} ({w['datum']}, {w['boerse']}), "
            f"200-Tage-Linie {w['sma200']} ({w['abstand_pct']:+.1f} %), RSI {w['rsi14']}",
            f"  Signal seit {w['signal_seit']} ({w['tage_seit']} Tage)",
            f"  Test seit {t['seit']}: Regel {t['regel_pa']} % p.a. (max. {t['regel_dd']} %), "
            f"Halten {t['halten_pa']} % p.a. (max. {t['halten_dd']} %)",
            "",
        ]
    zeilen.append("Nur Regelstand, keine Anlageberatung.")
    return "\n".join(zeilen)


def main(argv: list[str]) -> int:
    befehl = argv[0] if argv else "signale"
    try:
        if befehl == "liste":
            werte = lade_liste()
            print(json.dumps(werte, ensure_ascii=False) if "--json" in argv else
                  "\n".join(f"{w['isin']}  {w['name']}  [{w['ticker']}, {w['waehrung']}]" for w in werte) or "Liste ist leer.")
        elif befehl == "hinzufuegen" and len(argv) > 1:
            ticker = argv[argv.index("--ticker") + 1] if "--ticker" in argv else None
            e = hinzufuegen(argv[1], ticker)
            print(f"Aufgenommen: {e['name']} (ISIN {e['isin']}), Kurs über {e['ticker']} in {e['waehrung']}, {e['boerse']}")
        elif befehl == "entfernen" and len(argv) > 1:
            entfernen(argv[1])
            print(f"Entfernt: {argv[1].upper()}")
        elif befehl == "signale":
            werte = signale()
            print(json.dumps(werte, ensure_ascii=False) if "--json" in argv else text(werte))
        else:
            print(__doc__)
            return 2
    except ValueError as err:
        print(f"Fehler: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
