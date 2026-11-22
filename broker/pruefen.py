"""ISIN prüfen lassen: nimmt eine ISIN in die Prüfliste auf (oder entfernt sie).

    python broker/pruefen.py hinzufuegen IE00B6R52259
    python broker/pruefen.py entfernen IE00B6R52259

Die Prüfliste ist getrennt von der Watchlist: geprüfte Werte erscheinen in der
App unter "Prüfen & Entdecken", bis du sie in die Watchlist übernimmst.
"""
import json
import sys
from pathlib import Path

import broker

LISTE = Path(__file__).resolve().parent.parent / "pruefliste.json"


def isin_gueltig(isin: str) -> bool:
    """Prüfziffer nach ISO 6166: Buchstaben zu Zahlen, dann Luhn-Verfahren."""
    if len(isin) != 12 or not isin[:2].isalpha() or not isin[2:11].isalnum() or not isin[11].isdigit():
        return False
    ziffern = "".join(str(int(c, 36)) for c in isin[:11])
    summe = 0
    for i, z in enumerate(reversed(ziffern)):
        n = int(z)
        if i % 2 == 0:
            n *= 2
            n = n - 9 if n > 9 else n
        summe += n
    return (10 - summe % 10) % 10 == int(isin[11])


def lade():
    return json.loads(LISTE.read_text())["werte"] if LISTE.exists() else []


def speichere(werte):
    LISTE.write_text(json.dumps({"werte": werte}, ensure_ascii=False, indent=2) + "\n")


def main(argv):
    if len(argv) < 2 or argv[0] not in ("hinzufuegen", "entfernen"):
        print(__doc__)
        return 2
    isin = argv[1].strip().upper()
    werte = lade()
    if argv[0] == "entfernen":
        rest = [w for w in werte if w["isin"] != isin]
        speichere(rest)
        print(f"Entfernt: {isin}" if len(rest) < len(werte) else f"{isin} stand nicht auf der Prüfliste.")
        return 0
    if isin in broker.KRYPTO:
        print("Krypto (BTC, ETH) bitte direkt in die Watchlist aufnehmen.", file=sys.stderr)
        return 1
    if not isin_gueltig(isin):
        print(f"Fehler: {isin} ist keine gültige ISIN (Prüfziffer passt nicht). Bitte auf Tippfehler prüfen.", file=sys.stderr)
        return 1
    if any(w["isin"] == isin for w in werte):
        print(f"{isin} ist schon auf der Prüfliste.")
        return 0
    try:
        info = broker.finde(isin)
    except ValueError as err:
        print(f"Fehler: {err}", file=sys.stderr)
        return 1
    werte.append({"isin": isin, **info})
    speichere(werte)
    print(f"Zur Prüfung aufgenommen: {info['name']} (ISIN {isin}), {info['ticker']} in {info['waehrung']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
