# Implementation Plan: Déploiement Cloud Run

Spec de référence : [specs/deploy-cloud-run.md](../specs/deploy-cloud-run.md)

## Overview

Rendre lightweight-extraction accessible sur une URL Cloud Run publique
(`extraction-pv`, `europe-west9`), protégée par un middleware Basic Auth
applicatif (pas de brique GCP), avec secrets (clés API + credentials Basic
Auth) en Secret Manager. SQLite locale conservée telle quelle — pas de tâche
de migration de persistance, conformément à la spec. Le plan suit une chaîne
majoritairement séquentielle : outillage local (gcloud), puis code (auth
middleware, testable et vérifiable sans aucune ressource GCP), puis
ressources GCP (APIs, secrets), puis déploiement, puis vérification.

## Architecture Decisions

- **Basic Auth applicatif, pas IAP/Identity Platform.** Décision déjà actée
  dans la spec (lien partageable sans compte Google). Implémenté comme un
  hook FastHTML plutôt qu'une lib externe — `fast_app()` expose `before`
  (`Beforeware`, hook pré-route avec accès à la requête) et `middleware`
  (middlewares Starlette classiques). Lequel des deux convient le mieux pour
  répondre `401 WWW-Authenticate: Basic` avant toute route est à vérifier à
  l'implémentation (Task 2, skill `source-driven-development`) plutôt que
  deviné ici — les deux sont exposés par la même signature `fast_app(...)`
  déjà utilisée dans `app/main.py`.
- **Credentials Basic Auth lus depuis l'environnement, jamais en dur.**
  `os.getenv("BASIC_AUTH_USER")` / `os.getenv("BASIC_AUTH_PASSWORD")`, même
  mécanisme que les clés API existantes (`app/config.py::load_env`). En local,
  ajoutés à `.env` (déjà gitignoré) ; sur Cloud Run, injectés comme variables
  d'environnement à partir de Secret Manager via `--set-secrets` — aucun
  changement de code entre les deux environnements.
- **`load_env()` ne nécessite aucune modification.** Il ne fait que compléter
  `os.environ` pour les clés absentes (`if key not in os.environ`) — sur Cloud
  Run, les secrets injectés par `--set-secrets` sont déjà dans `os.environ`
  avant le démarrage de Python, donc `load_env()` (qui ne trouvera pas de
  `.env` dans l'image, celui-ci étant gitignoré et non copié) est un no-op
  silencieux et sans danger dans ce contexte.
- **Pas de Dockerfile a priori.** `gcloud run deploy --source .` utilise les
  buildpacks, qui savent détecter un projet Python géré par `uv`
  (`pyproject.toml`/`uv.lock`). Si la détection échoue (Task 6), un Dockerfile
  minimal (`uv sync --frozen` + `CMD`) est le filet de sécurité déjà identifié
  dans la spec — pas anticipé en tâche séparée tant que le besoin n'est pas
  confirmé.
- **Toute commande gcloud facturable ou modifiant l'identité/le projet
  utilisateur est exécutée avec confirmation explicite avant lancement**
  (boundary "Ask first" de la spec) — `gcloud auth login`, activation d'API,
  création de secret, `gcloud run deploy`. Les commandes purement locales
  (code, tests) ne le nécessitent pas.

## Dependency Graph

```
Task 1: Installer gcloud CLI + auth + projet extraction-pv
    │                                             │
    ▼                                             ▼
Task 2: Middleware Basic Auth (app/auth.py)   Task 3: Activer les APIs GCP
    + tests + branchement app/main.py             (run, cloudbuild, secretmanager)
    │                                             │
    │                                             ▼
    │                                         Task 4: Secrets dans Secret Manager
    │                                             (clés API existantes + Basic Auth)
    │                                             │
    └─────────────────┬───────────────────────────┘
                       ▼
              Task 5: Premier déploiement Cloud Run
                       │
                       ▼
              Task 6: Vérification post-déploiement
                       │
                       ▼
              Task 7: Housekeeping (README, spec)
```

**Parallélisable** : Task 2 (code, aucune dépendance GCP) peut être menée en
parallèle de Task 1/3/4.

**Séquentiel obligatoire** : Task 1 avant Task 3 (projet/authentification
nécessaires pour activer des APIs) ; Task 3 avant Task 4 (l'API Secret
Manager doit être active) ; Task 5 nécessite Task 2 (middleware en place et
testé — boundary "Never `--allow-unauthenticated` sans le middleware actif")
ET Task 4 (secrets disponibles à référencer au déploiement) ; Task 6 après
Task 5 ; Task 7 en dernier.

## Task List

### Phase 1: Fondations (parallélisables)

- [x] Task 1: Installer/authentifier gcloud CLI, configurer le projet `extraction-pv`
- [x] Task 2: Middleware Basic Auth (`app/auth.py`) + tests + branchement dans `app/main.py`

### Checkpoint: Fondations
- [x] `uv run pytest -v -m "not live"` passe intégralement, y compris `tests/test_auth.py`
- [x] `gcloud config get-value project` retourne `extraction-pv`
- [x] Revue avec l'utilisateur avant de continuer

### Phase 2: Ressources GCP

- [x] Task 3: Activer les APIs Cloud Run, Cloud Build, Secret Manager
- [x] Task 4: Créer les secrets (clés API existantes + credentials Basic Auth) dans Secret Manager

### Checkpoint: Ressources GCP
- [x] `gcloud services list --enabled` liste `run.googleapis.com`,
      `cloudbuild.googleapis.com`, `secretmanager.googleapis.com`
- [x] `gcloud secrets list` liste tous les secrets attendus, aucune valeur en
      clair affichée dans la session ou committée
- [x] Revue avec l'utilisateur avant de continuer

### Phase 3: Déploiement

- [x] Task 5: Premier déploiement Cloud Run (`gcloud run deploy extraction-pv --source . --region europe-west9 --allow-unauthenticated --set-secrets=...`)
- [x] Task 6: Vérification post-déploiement (401 sans credentials, 200 avec, extraction bout-en-bout)

### Checkpoint: Déploiement
- [x] URL Cloud Run publique répond, protégée par Basic Auth
- [x] Une extraction PDF/NER réelle fonctionne sur le déploiement
- [x] Revue avec l'utilisateur avant de continuer

### Phase 4: Polish

- [x] Task 7: Housekeeping (README, cocher les success criteria de la spec)

### Checkpoint: Complete
- [x] Tous les success criteria de `specs/deploy-cloud-run.md` sont cochés
- [ ] Revue finale avec l'utilisateur

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| API exacte FastHTML (`before` vs `middleware`) pour intercepter avant toute route inconnue à ce stade | Medium | Vérifier via lecture de la lib installée à Task 2 (skill `source-driven-development`) plutôt que deviner. |
| Buildpacks échouent à détecter le projet `uv` (pas de `requirements.txt`) | Medium | Fallback Dockerfile minimal déjà identifié dans la spec — à activer seulement si Task 5 échoue avec cette cause précise (voir `cloud-run-basics` § "Native Dependency Error"). |
| Le lien partagé donne accès aux appels LLM sur les clés du porteur du projet, sans limite de quota au-delà du Basic Auth | Low (accepté explicitement, hors scope de la spec) | Ne pas partager le lien au-delà du cercle de démo prévu ; ouvert dans la spec, pas traité par ce plan. |
| Cold start / scale-to-zero réinitialise la base SQLite pendant une démo | Low (accepté explicitement, hors scope) | `--min-instances=1` reste une option non retenue à ce stade (Open Question de la spec) — pas de tâche dédiée. |
| Commande `gcloud` exécutée par erreur sans confirmation, créant une ressource facturable | Medium | Toute commande listée comme "Ask first" dans la spec est présentée à l'utilisateur avant exécution, jamais lancée en autonomie. |

## Open Questions

Reprises telles quelles de la spec — aucune ne bloque le début de
l'implémentation :
- Choix définitif entre `before`/`middleware` FastHTML pour le Basic Auth →
  tranché à Task 2.
- `--min-instances=1` → non traité par ce plan, laissé pour une itération
  ultérieure si besoin.
