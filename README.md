# Rohstoff-Kompass

Signal- und Risiko-Übersicht für Gold, Silber, Platin, Palladium, Kupfer, Öl (WTI/Brent) und Erdgas –
als Web-App für iPhone und Laptop. Gedacht als Hilfsmittel für manuelles CFD-Trading (z. B. Trading 212).

**Keine Anlageberatung, keine Gewinngarantie.** Der eingebaute 15-Jahres-Backtest zeigt, dass die Regeln
über alle Märkte nach Kosten etwa bei null landen; die Zahlen stehen offen in der App.

- `engine.py` – lädt Tageskurse, berechnet Signale und Backtest, schreibt `docs/data.json` (nur Python-Standardbibliothek)
- `docs/` – die App (statische Seite)
- `.github/workflows/update.yml` – aktualisiert die Daten stündlich an Werktagen

## Einrichten
1. GitHub → Settings → Pages → Source „Deploy from a branch“, Ordner `/docs` wählen.
2. Die angezeigte Adresse am iPhone in Safari öffnen → Teilen → „Zum Home-Bildschirm“.
3. Lokal testen: `python3 engine.py && python3 -m http.server -d docs`
