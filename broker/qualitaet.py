"""Qualitätsprüfung vor dem Veröffentlichen (Lean: Fehler stoppen, nicht weitergeben).

    python broker/qualitaet.py app/data

Bricht mit Fehler ab, wenn die Daten nicht veröffentlicht werden dürfen. Dann
bleibt in der App der letzte gute Stand. Schreibt außerdem einen Kurzbericht
für die GitHub-Ablaufübersicht, ohne Kurse erneut zu laden.
"""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

PFLICHT = ("isin", "name", "kurs", "signal", "abstand_pct", "rsi14", "datum", "gruppe")
MAX_ALTER_TAGE = 6       # deckt Wochenenden und Feiertage ab
MIN_ANTEIL_OK = 0.5      # mindestens die Hälfte der Werte muss Daten haben


def pruefe(ordner: Path) -> tuple[list[str], list[str], list[dict]]:
    fehler, warnungen = [], []
    werte = json.loads((ordner / "werte.json").read_text())["rows"]
    verlauf = json.loads((ordner / "verlauf.json").read_text())["rows"]
    ok = [r for r in werte if not r.get("fehler")]

    if not werte:
        fehler.append("Keine Werte erzeugt.")
    elif len(ok) / len(werte) < MIN_ANTEIL_OK:
        fehler.append(f"Nur {len(ok)} von {len(werte)} Werten haben Daten. Wahrscheinlich ist eine Kursquelle ausgefallen.")
    for r in werte:
        if r.get("fehler"):
            warnungen.append(f"{r['name']} ({r['isin']}): {r['fehler']}")
            continue
        fehlt = [f for f in PFLICHT if r.get(f) is None]
        if fehlt:
            fehler.append(f"{r['isin']}: Felder fehlen: {', '.join(fehlt)}")
        if r.get("kurs") is not None and not r["kurs"] > 0:
            fehler.append(f"{r['isin']}: unmöglicher Kurs {r['kurs']}")
        if r.get("rsi14") is not None and not 0 <= r["rsi14"] <= 100:
            fehler.append(f"{r['isin']}: RSI außerhalb 0 bis 100")
        if r.get("datum"):
            alter = (date.today() - datetime.strptime(r["datum"], "%Y-%m-%d").date()).days
            if alter > MAX_ALTER_TAGE:
                warnungen.append(f"{r['name']} ({r['isin']}): letzter Kurs ist {alter} Tage alt")
    isins = [r["isin"] for r in werte]
    if len(isins) != len(set(isins)):
        fehler.append("Ein Wert steht doppelt in den Daten.")
    if ok and not verlauf:
        fehler.append("Kursverlauf ist leer.")
    return fehler, warnungen, werte


def bericht(werte: list[dict], fehler: list[str], warnungen: list[str]) -> str:
    z = ["## BroKer Lauf", ""]
    if fehler:
        z += ["**Nicht veröffentlicht**, die App zeigt weiter den letzten guten Stand:", ""] + [f"- {f}" for f in fehler] + [""]
    else:
        z += ["Daten geprüft und veröffentlicht.", ""]
    kern = [r for r in werte if r.get("gruppe") in ("Watchlist", "Baustein") and not r.get("fehler")]
    neu = [r for r in kern if r.get("neu")]
    if neu:
        z += ["**Neue Signale:**", ""] + [f"- {r['name']} ({r['isin']}): jetzt {r['signal']}" for r in neu] + [""]
    z += ["| Wert | ISIN | Signal | Abstand Linie | RSI |", "|---|---|---|---|---|"]
    z += [f"| {r['name']} | {r['isin']} | {r['signal']} | {r['abstand_pct']:+.1f} % | {r['rsi14']:.0f} |" for r in kern]
    if warnungen:
        z += ["", "**Hinweise:**", ""] + [f"- {w}" for w in warnungen]
    z += ["", "Nur Regelstand, keine Anlageberatung."]
    return "\n".join(z) + "\n"


def main(argv: list[str]) -> int:
    ordner = Path(argv[0] if argv else "app/data")
    fehler, warnungen, werte = pruefe(ordner)
    text = bericht(werte, fehler, warnungen)
    ziel = os.environ.get("GITHUB_STEP_SUMMARY")
    if ziel:
        with open(ziel, "a") as f:
            f.write(text)
    print(text)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
