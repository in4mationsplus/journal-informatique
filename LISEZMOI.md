# Journal informatique

Les news informatiques du jour, sans doublons, lues en français en
15 minutes au plus. Deux éditions : le matin et à midi.

- `journal.py preparer` : flux RSS → `travail/articles.json` (GitHub Actions)
- tâche programmée Claude Code : suit `CONSIGNES.md` → `travail/redaction.json`
- `journal.py finir` : voix, chapitres, `docs/flux.xml`, `docs/editions.json`
  (GitHub Actions, déclenché par le push de la rédaction)

Les MP3 sont dans la release `episodes`. Le flux de podcast est publié par
GitHub Pages depuis `docs/`.
