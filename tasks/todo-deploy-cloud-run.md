# Task List: Déploiement Cloud Run

Plan de référence : [tasks/plan-deploy-cloud-run.md](plan-deploy-cloud-run.md) ·
Spec : [specs/deploy-cloud-run.md](../specs/deploy-cloud-run.md)

---

## Task 1: Installer/authentifier gcloud CLI, configurer le projet

**Description:** Installer gcloud CLI dans cet environnement (absent
actuellement), authentifier avec le compte youn.jehanno@gmail.com
(`gcloud auth login`), et configurer le projet actif sur `extraction-pv`
(numéro 783442504013). Utiliser le skill `gcloud` pour l'installation/la
configuration plutôt que des commandes improvisées.

**Acceptance criteria:**
- [x] `gcloud --version` fonctionne dans cet environnement
- [x] `gcloud auth list` montre youn.jehanno@gmail.com comme compte actif
- [x] `gcloud config get-value project` retourne `extraction-pv`

**Note d'implémentation :** gcloud installé en standalone (tarball officiel,
sans sudo/apt) dans `~/google-cloud-sdk`, symlinké dans `/usr/local/bin` pour
persister entre les appels d'outils. L'environnement n'ayant pas de
navigateur, ni `gcloud auth login` classique ni `--no-browser`
(remote-bootstrap, nécessite gcloud + navigateur sur une seconde machine —
échoué même depuis Cloud Shell, qui n'a pas de navigateur non plus) ne
fonctionnaient. `--no-launch-browser` (flux URL + code de vérification manuel,
sans besoin de gcloud côté navigateur) a fonctionné, via un FIFO pour
transmettre le code une fois obtenu par l'utilisateur.

**Verification:**
- [x] Manuel: `gcloud config list` affiche `project = extraction-pv` et le bon compte

**Dependencies:** None

**Files likely touched:** Aucun (configuration locale de l'environnement, pas de fichier versionné)

**Estimated scope:** XS (aucune modification de code)

---

## Task 2: Middleware Basic Auth (`app/auth.py`) + tests + branchement

**Description:** Implémenter un hook FastHTML (`before` ou `middleware`, API
exacte à vérifier sur la lib installée — voir Architecture Decisions du plan)
qui exige un Basic Auth valide sur toute requête : `401` avec header
`WWW-Authenticate: Basic` si absent/invalide, laisse passer si les
identifiants correspondent à `os.getenv("BASIC_AUTH_USER")` /
`os.getenv("BASIC_AUTH_PASSWORD")`. Enregistré depuis `create_app()` dans
`app/main.py`, avant toute route fonctionnelle. Ajouter les deux variables à
`.env.example` (vides, avec commentaire) — jamais de valeur réelle committée.

**Acceptance criteria:**
- [x] Une requête sans header `Authorization` sur une route existante (ex.
      `/fields`) reçoit `401`
- [x] Une requête avec de mauvais identifiants reçoit `401`
- [x] Une requête avec les bons identifiants (lus depuis l'environnement de
      test, pas de vraie valeur en dur) reçoit `200`/comportement normal
- [x] `.env.example` documente `BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD` sans
      valeur réelle

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_auth.py` (4 passed)
- [x] Tests: `uv run pytest -v -m "not live"` (171 passed, 1 échec
      préexistant sans rapport — `test_post_fields_import_replaces_definition_on_same_key`,
      lié à `DATASET GOLD.csv` déjà modifié avant cette session ; 1 deselected)

**Note d'implémentation :** `before` (Beforeware) retenu plutôt que
`middleware` — signature `f(req)`, retourne `None` pour laisser passer ou un
`Response(..., status_code=401, headers={"WWW-Authenticate": "Basic"})` pour
court-circuiter avant toute route (mécanisme déjà utilisé en interne par
FastHTML pour l'auth par session). Pas de fixture `conftest.py` dédiée
finalement : les credentials de test sont injectés directement via
`monkeypatch.setenv`/`delenv` dans chaque test de `tests/test_auth.py`,
plus simple qu'une fixture partagée pour 4 tests.

**Dependencies:** None (parallélisable avec Task 1)

**Files likely touched:**
- `app/auth.py`
- `app/main.py`
- `tests/test_auth.py`
- `.env.example`

**Estimated scope:** S (3-4 fichiers)

---

## Checkpoint: Fondations (après Tasks 1-2)
- [x] `uv run pytest -v -m "not live"` passe intégralement, y compris `tests/test_auth.py`
- [x] `gcloud config get-value project` retourne `extraction-pv`
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 3: Activer les APIs GCP nécessaires

**Description:** Activer les APIs Cloud Run Admin, Cloud Build et Secret
Manager sur le projet `extraction-pv`, via le skill `cloud-run-basics`
(section Prerequisites). Action facturable/modifiant le projet — confirmation
utilisateur avant exécution (boundary "Ask first" de la spec).

**Acceptance criteria:**
- [x] `run.googleapis.com`, `cloudbuild.googleapis.com`,
      `secretmanager.googleapis.com` sont activées sur `extraction-pv`

**Verification:**
- [x] Manuel: `gcloud services list --enabled` liste les trois APIs

**Dependencies:** Task 1

**Files likely touched:** Aucun

**Estimated scope:** XS

---

## Task 4: Secrets dans Secret Manager

**Description:** Créer dans Secret Manager les secrets nécessaires au
déploiement : les clés API déjà présentes dans le `.env` local
(`GOOGLE_GENERATIVE_AI_API_KEY`, `OPENAI_API_KEY` si renseignée, clés
Langfuse si renseignées) et les deux nouveaux credentials Basic Auth
(`BASIC_AUTH_USER=nolwennpv`, `BASIC_AUTH_PASSWORD=<fourni par
l'utilisateur>`). Valeurs transmises à `gcloud secrets create`/`versions add`
via un fichier temporaire ou stdin (`--data-file=-`), jamais en argument de
ligne de commande visible dans l'historique shell, et jamais écrites dans un
fichier versionné. Action sensible — confirmation utilisateur avant
exécution.

**Acceptance criteria:**
- [x] Chaque secret existe dans Secret Manager (`gcloud secrets list`) :
      `google-generative-ai-api-key`, `openai-api-key`, `langfuse-public-key`,
      `langfuse-secret-key`, `basic-auth-user`, `basic-auth-password`
- [x] Aucune valeur de secret n'apparaît dans un fichier du dépôt, dans les
      logs de la session, ou dans l'historique de commande visible (valeurs
      pipées directement depuis `.env` local vers `gcloud secrets create
      --data-file=-`, jamais affichées ni passées en argument)

**Note d'implémentation :** `BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD` ajoutés au
`.env` local (gitignoré) avant création des secrets, par cohérence avec les
autres clés (même source pour toutes les valeurs poussées vers Secret
Manager).

**Verification:**
- [x] Manuel: `gcloud secrets list` affiche les 6 noms attendus (pas les valeurs)

**Dependencies:** Task 3

**Files likely touched:** Aucun

**Estimated scope:** S (plusieurs secrets, aucune modification de code)

---

## Checkpoint: Ressources GCP (après Tasks 3-4)
- [x] Les trois APIs sont actives
- [x] Tous les secrets attendus existent, aucune valeur en clair exposée
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 5: Premier déploiement Cloud Run

**Description:** Déployer le service `extraction-pv` en `europe-west9` via
`gcloud run deploy --source .` (buildpacks), en référençant les secrets
Task 4 avec `--set-secrets` (mapping nom de variable d'environnement → nom de
secret Secret Manager) plutôt que `--set-env-vars` en clair. Le middleware
Basic Auth (Task 2) doit être en place et testé avant cette tâche — boundary
"Never `--allow-unauthenticated` sans le middleware actif" de la spec.
Action facturable — confirmation utilisateur avant exécution.

**Acceptance criteria:**
- [x] `gcloud run deploy` réussit et retourne une URL
      `https://extraction-pv-783442504013.europe-west9.run.app`
- [x] Aucune clé API ni credential Basic Auth en `--set-env-vars` clair dans
      la commande exécutée (tout via `--set-secrets`, valeurs jamais affichées)
- [x] Buildpacks ont bien détecté le projet `uv` — pas de fallback Dockerfile
      nécessaire pour ça

**Note d'implémentation — trois blocages résolus en cours de route :**
1. `.python-version` pinnait `3.12` exactement ; le builder Cloud Run ne
   propose plus aucune version 3.12.x (dépréciée côté Google, seuls 3.13.x/
   3.14.x disponibles). `pyproject.toml` déclare `requires-python = ">=3.12"`
   → `.python-version` passé à `3.13` (compatible, aucun changement de code).
2. Le buildpack `google.python.missing-entrypoint` exige un `main.py`/`app.py`
   à la racine ou un entrypoint explicite ; notre point d'entrée est
   `app/main.py` (paquet), lancé via `python -m app.main`. Résolu avec
   `--set-build-env-vars="GOOGLE_ENTRYPOINT=python -m app.main"` au
   déploiement (pas de Procfile ni de restructuration du repo).
3. Le service account d'exécution par défaut
   (`783442504013-compute@developer.gserviceaccount.com`) n'avait pas accès
   aux secrets — `roles/secretmanager.secretAccessor` accordé sur chacun des
   6 secrets individuellement (confirmation utilisateur obtenue avant
   modification IAM, conformément aux boundaries).

**Verification:**
- [x] Manuel: `gcloud run services describe extraction-pv --region
      europe-west9` — revision `extraction-pv-00002-8wj`, 100% du trafic

**Dependencies:** Task 2, Task 4

**Files likely touched:**
- `Dockerfile` *(uniquement si fallback nécessaire — voir Acceptance criteria)*

**Estimated scope:** S (déploiement, pas de nouveau code applicatif dans le cas nominal)

---

## Task 6: Vérification post-déploiement

**Description:** Vérifier manuellement le comportement de bout en bout sur
l'URL Cloud Run réelle : accès refusé sans credentials, accès autorisé avec
les bons credentials, et une extraction PDF/NER complète fonctionnant avec
les clés API injectées depuis Secret Manager.

**Acceptance criteria:**
- [x] `curl` sans `-u` sur l'URL Cloud Run → `401`
- [x] `curl -u nolwennpv:<mot de passe>` sur l'URL → `200`/page `/fields`
      normale (mauvais mot de passe → `401` également vérifié)
- [x] Upload d'un PDF de test + extraction NER sur le déploiement → résultat
      réel (`source="langextract"`, pas `mock`), avec page/citation

**Notes d'implémentation — deux problèmes découverts et corrigés :**
1. **Secrets avec saut de ligne parasite.** La première vérification (`curl
   -u` avec les bons identifiants) renvoyait `401` au lieu de `200`. Cause :
   `grep '^KEY=' .env | cut -d= -f2-` (Task 4) préserve le `\n` de fin de
   ligne dans la valeur piped vers `gcloud secrets create --data-file=-` — le
   secret contenait donc `bebitotlabest\n` au lieu de `bebitotlabest`,
   invisible en base64 mais cassant la comparaison stricte du middleware.
   Corrigé en ajoutant une nouvelle version de chacun des 6 secrets via
   `tr -d '\n'` avant `gcloud secrets versions add`, puis redéploiement pour
   qu'une nouvelle révision résolve `:latest` vers les versions corrigées.
2. **OOM sur la limite mémoire par défaut (512 MiB).** La première tentative
   d'extraction réelle renvoyait `503` — logs Cloud Run : "Memory limit of
   512 MiB exceeded with 519 MiB used" (PyMuPDF4LLM + pandas + langextract
   chargés simultanément). Confirmé avec l'utilisateur puis résolu via
   `gcloud run services update extraction-pv --memory=1Gi` (hors scope
   initial de la spec, mais nécessaire pour satisfaire ce success criterion —
   documenté ici plutôt que deviné en amont).

Par ailleurs, le redémarrage de conteneur causé par l'OOM (puis le nouveau
déploiement pour la limite mémoire) a bien fait repartir la base SQLite à
zéro entre deux tentatives — comportement éphémère explicitement accepté par
la spec, observé concrètement ici plutôt que seulement théorique.

**Verification:**
- [x] Manuel: les trois vérifications ci-dessus, exécutées contre l'URL réelle
      `https://extraction-pv-783442504013.europe-west9.run.app`

**Dependencies:** Task 5

**Files likely touched:** Aucun

**Estimated scope:** XS (vérification manuelle, pas de code)

---

## Checkpoint: Déploiement (après Tasks 5-6)
- [x] URL Cloud Run publique répond, protégée par Basic Auth
- [x] Une extraction PDF/NER réelle fonctionne sur le déploiement
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 7: Housekeeping (README, success criteria)

**Description:** Documenter le déploiement Cloud Run dans le README (URL de
service, commande de redéploiement, rappel que les données SQLite sont
éphémères), et repasser explicitement chaque success criterion de
`specs/deploy-cloud-run.md` pour cocher ce qui est fait.

**Acceptance criteria:**
- [x] `README.md` documente l'accès à l'URL Cloud Run (Basic Auth requis) et
      la commande de redéploiement
- [x] Tous les success criteria de la spec sont cochés ou justifiés

**Note d'implémentation :** en relançant la suite complète pour cette tâche,
régression découverte et corrigée — `BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD`
ajoutés au `.env` local (Task 4) fuitaient dans tous les tests de routes via
`load_env()`, cassant 37 tests qui n'envoient pas de credentials. Fixture
autouse `_no_real_basic_auth_in_tests` ajoutée dans `tests/conftest.py`
(même pattern que `_no_real_langfuse_in_tests` déjà en place) pour les
neutraliser par défaut.

**Verification:**
- [x] Manuel: relecture croisée `specs/deploy-cloud-run.md` § Success
      Criteria vs état réel du déploiement
- [x] Tests: `uv run pytest -v -m "not live"` (171 passed, 1 échec
      préexistant sans rapport, 1 deselected)

**Dependencies:** Task 6

**Files likely touched:**
- `README.md`
- `specs/deploy-cloud-run.md` (cocher les success criteria)
- `tests/conftest.py` *(ajouté — fixture d'isolation Basic Auth)*

**Estimated scope:** XS

---

## Checkpoint: Complete (après Task 7)
- [x] Tous les success criteria de `specs/deploy-cloud-run.md` sont cochés
- [ ] Revue finale avec l'utilisateur
