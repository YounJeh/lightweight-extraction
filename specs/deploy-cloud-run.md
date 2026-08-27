# Spec: Déploiement Cloud Run

## Objective
Rendre lightweight-extraction accessible via une URL Cloud Run publique, protégée
par une authentification applicative minimale, pour un usage démo ponctuel du
porteur du projet (youn.jehanno@gmail.com). Pas de réécriture de la
persistance : SQLite locale conservée telle quelle, perte de données acceptée
au redémarrage du conteneur (scale-to-zero, redéploiement).

Utilisateur : le porteur du projet + les personnes à qui il partage le lien et
les identifiants pour une démo. Succès = une URL `https://...run.app`
accessible depuis n'importe quel navigateur, protégée par login/mot de passe,
qui sert l'app fonctionnelle (gestion des champs + extraction PDF/NER) sans
qu'aucune clé API n'apparaisse dans le code, l'image ou les logs.

## Tech Stack
- Runtime : Python 3.12, python-fasthtml (ASGI/uvicorn via `fasthtml.serve()`)
- Déploiement : Cloud Run, build via `Dockerfile` à la racine (pas buildpacks
  — nécessaire depuis l'ajout de l'OCR, voir "Incident" dans
  `choix_techniques.md` : le build source-based ne garantit pas que
  `opencv-python-headless` l'emporte sur `opencv-python`)
- Mémoire : 2 Gi (RapidOCR/OpenCV/onnxruntime ont une empreinte réelle — un
  document réel a dépassé 1 Gi, voir `choix_techniques.md`)
- Secrets : Google Secret Manager (clés API Gemini/OpenAI/Langfuse + identifiants Basic Auth)
- Projet GCP : `extraction-pv` (numéro 783442504013), compte youn.jehanno@gmail.com
- Région : `europe-west9` (Paris)

## Commands
Déploiement (exécuté par Claude Code depuis cet environnement — gcloud CLI à
installer au préalable — avec confirmation utilisateur avant toute action
facturable/sensible) :
```bash
gcloud auth login
gcloud config set project extraction-pv
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com --quiet
gcloud run deploy extraction-pv --source . --region europe-west9 --memory=2Gi --allow-unauthenticated --clear-base-image --quiet
```

Tests (inchangé, local) :
```bash
uv run pytest -v -m "not live"
```

Dev local (inchangé) :
```bash
uv run python -m app.main
```

## Project Structure
Aucun nouveau répertoire de premier niveau. Ajouts prévus :
```
app/auth.py                  → middleware Basic Auth applicatif (nouveau)
tests/test_auth.py           → tests du middleware d'authentification (nouveau)
specs/deploy-cloud-run.md    → cette spec
tasks/plan-deploy-cloud-run.md, tasks/todo-deploy-cloud-run.md → Phase 2/3 (suite)
```
`Dockerfile` + `.dockerignore` à la racine (ajoutés après le passage à
l'OCR — voir "Incident" dans `choix_techniques.md`), pas de build buildpack
source-based.

## Code Style
Le repo utilise des closures + enregistrement explicite de route (voir
`app/routes/fields.py`) :
```python
def register_fields_routes(app, repo: FieldRepository):
    @app.get("/fields")
    def get():
        return page("Champs", ...)
```
Le middleware d'auth suit le même style : une fonction
`register_basic_auth(app, username: str, password: str)` appelée depuis
`create_app()` dans `app/main.py`, avant l'enregistrement des routes
fonctionnelles — pas de classe, pas de framework d'auth externe.

Commentaires : uniquement pour expliquer un "pourquoi" non évident (convention
déjà en place, voir `app/db.py`/`app/main.py`).

## Testing Strategy
- Framework existant : pytest (`uv run pytest -v -m "not live"`)
- Nouveau `tests/test_auth.py` : 401 sans credentials, 200 avec les bons
  credentials, 401 avec de mauvais credentials — credentials de test injectés
  via variable d'environnement, sans appel à Secret Manager réel
- Pas de test end-to-end contre le Cloud Run déployé dans la suite pytest ; la
  vérification post-déploiement se fait manuellement (`curl`/navigateur sur
  l'URL Cloud Run)

## Boundaries
- **Toujours faire** : lancer `uv run pytest -v -m "not live"` avant tout
  déploiement ; ne jamais committer de secret (`.env`, identifiants Basic
  Auth) ; utiliser les skills Google du repo (`cloud-run-basics`,
  `google-cloud-recipe-auth`, `gcloud`, etc.) plutôt que des commandes gcloud
  improvisées
- **Demander d'abord** : toute commande `gcloud` créant/modifiant une
  ressource facturable (déploiement, activation d'API, création de secret) ;
  changer la région ou le nom du service une fois choisis ; toute évolution
  vers une persistance non-éphémère (Cloud SQL, GCS FUSE) — hors scope
- **Ne jamais faire** : commiter une clé API ou un mot de passe en clair ;
  déployer avec `--allow-unauthenticated` sans le middleware Basic Auth en
  place ; changer le mécanisme de persistance SQLite dans le cadre de ce
  déploiement

## Success Criteria
- [x] `gcloud run deploy` réussit et retourne une URL
      `https://extraction-pv-*.europe-west9.run.app` —
      `https://extraction-pv-783442504013.europe-west9.run.app`
- [x] L'URL sans credentials retourne 401 (Basic Auth actif)
- [x] L'URL avec les bons credentials affiche `/fields` (comportement
      identique au local)
- [x] Une extraction PDF/NER fonctionne de bout en bout sur le déploiement
      (clé Gemini lue depuis Secret Manager, pas d'erreur d'auth GCP) —
      vérifié avec un PDF réel, `source="langextract"`, page + citation
- [x] Aucune clé API ni mot de passe en clair dans le code, les logs Cloud
      Run, ou l'historique git — secrets créés en pipant directement depuis
      `.env` vers Secret Manager, jamais affichés ni committés
- [x] `uv run pytest -v -m "not live"` passe, y compris le nouveau
      `tests/test_auth.py`

## Open Questions
- Nom d'utilisateur/mot de passe du Basic Auth : à choisir par l'utilisateur
  avant l'implémentation (ne pas générer/stocker un mot de passe sans accord
  explicite)
- `--min-instances=1` pour limiter les cold starts pendant une session de
  démo, ou accepter le scale-to-zero par défaut ? Hors scope initial (direction
  minimale) ; à réévaluer si la démo dure longtemps
- Aucune protection de quota/dépense au-delà du Basic Auth n'est prévue dans
  cette spec — le lien partagé donne accès aux appels LLM sur les clés du
  porteur du projet
