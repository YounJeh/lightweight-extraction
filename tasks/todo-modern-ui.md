# Task List: UI moderne et épurée

Plan : [tasks/plan-modern-ui.md](plan-modern-ui.md) · Spec : [specs/modern-ui.md](../specs/modern-ui.md)

- [x] Task 1: `static/style.css` — variables, reset, layout `app-shell` (sidebar/main), composants génériques (`.card`, `.btn-primary`, `.btn-danger`, `.badge`, `.chip`, `.banner-error`, `.empty-state`)
- [x] Task 2: `app/main.py` — `fast_app(pico=False, hdrs=(Link(rel="stylesheet", href="/static/style.css"), Meta(name="viewport", ...)))`
- [x] Task 3: `app/ui/layout.py` — sidebar avec nav Champs/Extraction, état actif, grid `app-shell`
- [x] Task 4: `app/ui/components.py` — champs en cartes (liste + formulaire création), boutons stylés
- [x] Task 5: `app/ui/components.py` — extraction (upload, chips de champs, historique des runs, page résultat, badge mock)
- [x] Task 6: `uv run pytest -v` (38/38 sans modif de test) + revue via HTML rendu (pas de navigateur GUI dans cet environnement)

**Vérification finale :** cases à cocher de `specs/modern-ui.md` § Success Criteria.
