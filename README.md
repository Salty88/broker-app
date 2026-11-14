# BroKer

Dein Trading-Informant als App fürs iPhone. BroKer beobachtet Werte per ISIN und meldet, was die Regel "investiert, solange der Kurs über seinem 200-Tage-Durchschnitt liegt" gerade sagt: Signal, Entwicklung über Tag, Monat, Quartal und Jahr, Kursverlauf und Hinweise, wenn sich etwas Neues ergibt.

> Nur Regelstand, keine Anlageberatung. BroKer sagt keine Kurse voraus. Du entscheidest.

## App öffnen

1. Auf dem iPhone in Safari die GitHub-Pages-Adresse dieses Repositorys öffnen.
2. Teilen-Symbol, dann **Zum Home-Bildschirm**. BroKer startet danach wie eine App.

## Aktualisieren

- **Automatisch:** täglich um 07:30 UTC (8:30 Uhr Winterzeit, 9:30 Uhr Sommerzeit in Berlin).
- **Auf Knopfdruck:** In der App **Jetzt aktualisieren** tippen, dann auf GitHub **Run workflow**. Nach etwa 2 Minuten ist der neue Stand da.
- **Neuer Wert:** **Run workflow** und im Feld `isin` die ISIN aus der Trade-Republic-App eintragen (Krypto: `BTC` oder `ETH`). Zum Entfernen das Feld `entfernen` nutzen.

## Aufbau

| Datei | Zweck |
|---|---|
| `watchlist.json` | Deine Werte (ISIN, Börsenplatz, Währung) |
| `broker/broker.py` | ISIN suchen, Kurse laden, Signal und Test berechnen |
| `broker/daten.py` | Erzeugt die App-Daten (`app/data/werte.json`, `verlauf.json`) inklusive Beispiel-Bausteinen |
| `app/` | Die App: eine Seite, Symbol und Manifest |
| `.github/workflows/broker.yml` | Täglicher Lauf und Knopf "Run workflow", veröffentlicht die App über GitHub Pages |

Kursquellen: Yahoo Finance (Aktien, ETFs, bevorzugt Euro-Börsenplätze) und Binance (Krypto), nur abgeschlossene Tageskerzen.
