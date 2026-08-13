# Implementation Plan: UI moderne et épurée

Spec de référence : [specs/modern-ui.md](../specs/modern-ui.md)

## Overview

Restyle pur — pas de nouvelle logique métier. Deux tranches : (1) fondations
CSS + layout/sidebar, (2) restyle des composants par page. Aucun changement
aux routes/repositories/tools.

## Dependency Graph

```
Task 1: static/style.css (variables + reset + layout de base)
    │
    ▼
Task 2: app/main.py — brancher hdrs (pico=False, Link vers /static/style.css)
    │
    ▼
Task 3: app/ui/layout.py — sidebar + grid app-shell + état actif
    │
    ▼
Task 4: app/ui/components.py — cartes champs (liste + formulaire)
    │
    ▼
Task 5: app/ui/components.py — cartes extraction (upload, chips, résultats, historique)
    │
    ▼
Task 6: Vérification — pytest + revue visuelle manuelle + ajustements
```

Séquentiel : chaque tâche dépend du CSS/layout posé par la précédente.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Changer un texte par erreur casse un test | Medium | Diff minutieux du texte affiché avant/après chaque composant ; lancer pytest après chaque tâche. |
| PicoCSS désactivé casse un rendu implicite (ex. `<table>` par défaut) | Low | On restructure `fields_table` en cartes de toute façon (Task 4), donc plus de dépendance à Pico. |
| Pas de navigateur graphique dans l'environnement pour vérifier visuellement | Medium | Vérification via capture HTML/curl + revue de la CSS ; proposer une capture d'écran si un outil browser est disponible. |

## Open Questions

Aucune.
