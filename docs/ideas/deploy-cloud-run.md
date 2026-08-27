# Déploiement Cloud Run

## Problem Statement
Comment rendre lightweight-extraction accessible via une URL publique sur Cloud Run,
pour un usage démo ponctuel, sans reconstruire l'app en service multi-utilisateur ?

## Recommended Direction
Déploiement minimal : `gcloud run deploy --source .` (buildpacks, pas de Dockerfile),
`fasthtml.serve()` respecte déjà `PORT`/`0.0.0.0` donc aucun changement réseau requis.
Clés API (`GOOGLE_GENERATIVE_AI_API_KEY`, `OPENAI_API_KEY`, Langfuse) passées via
Secret Manager (`--set-secrets`), jamais en clair dans l'image ou en env var brute.

SQLite locale conservée telle quelle — la perte de données au redémarrage du
conteneur (scale-to-zero, redéploiement) est acceptée : usage démo ponctuel,
données de test non sensibles.

Une authentification minimale est ajoutée par-dessus l'accès public (le lien reste
partageable sans compte Google, mais protégé par un secret simple) — le mécanisme
exact (basic auth applicatif vs autre) reste à trancher en phase de spec.

## Key Assumptions to Validate
- [ ] Perte de données au redémarrage du conteneur acceptable — à reconfirmer si l'usage dépasse la démo ponctuelle initialement prévue
- [ ] Cloud Build buildpacks détecte correctement le projet `uv` (pyproject.toml + uv.lock) sans Dockerfile — à vérifier au premier déploiement, sinon fallback Dockerfile minimal
- [ ] Le mécanisme d'authentification minimale doit rester compatible avec un lien partageable sans compte Google (pas l'auth IAM Cloud Run, qui exige un compte Google identifié)
- [ ] Timeout Cloud Run par défaut suffisant pour la latence d'un appel LLM (Gemini/OpenAI) pendant l'extraction NER

## MVP Scope
- Déploiement Cloud Run source-based (buildpacks), service `extraction-pv` (ou nom similaire), région à définir
- Secrets (clés API) via Secret Manager, montés au déploiement
- Authentification applicative minimale (à spécifier) devant l'app
- SQLite éphémère, aucune persistance additionnelle (pas de GCS FUSE, pas de Cloud SQL)
- Pas de CI/CD — déploiement manuel via une commande `gcloud`

## Not Doing (and Why)
- Cloud SQL / persistance durable — usage démo ponctuel, pas de besoin multi-utilisateur simultané pour l'instant
- Cloud Storage FUSE pour SQLite — complexité inutile tant que la perte de données au redémarrage est acceptée
- CI/CD (Cloud Build trigger) — un déploiement manuel ponctuel suffit pour une démo
- IAP / auth Google — exigerait un compte Google pour chaque utilisateur invité, incompatible avec un lien simplement partageable

## Open Questions
- Quel mécanisme précis pour l'authentification minimale (basic auth applicatif, cookie de session avec mot de passe partagé, autre) ?
- Région Cloud Run à utiliser pour le projet `extraction-pv` ?
- Nom du service Cloud Run ?

## Contexte projet GCP
- Compte : youn.jehanno@gmail.com
- Projet : extraction-pv (numéro 783442504013)
