# Spec : Pipeline NuExtract (spike de comparaison)

## Objective

Comparer, sur le dataset gold, le pipeline actuel (PyMuPDF4LLM + LangExtract)
à un second pipeline basé sur NuExtract — serveur vLLM auto-hébergé, **déjà
déployé**, exposant une API OpenAI-compatible — qui extrait directement
depuis les pages du PDF rendues en images, sans étape de markdown ni d'OCR
applicatif (celui-ci reste entièrement du côté du pipeline actuel).

**Succès =** sur un sous-ensemble (ou l'ensemble) du dataset gold, un score
précision/recall/F1 par champ pour le pipeline NuExtract, produit par un
script autonome, sans modification du pipeline existant ni de `app/`.

Utilisateur : le porteur du projet (youn.jehanno@gmail.com), seul utilisateur
de ce dépôt.

Issu d'une session `idea-refine` — one-pager de cadrage :
[docs/ideas/nuextract-pipeline-spike.md](../docs/ideas/nuextract-pipeline-spike.md).

## Tech Stack

- Python 3.12/3.13, `uv` (inchangé).
- Client HTTP : SDK `openai` — **déjà résolu transitivement** dans
  `uv.lock` (via `langextract[openai]`), aucune nouvelle dépendance à
  ajouter. Pointé vers `base_url=NUEXTRACT_BASE_URL` (`OpenAI(base_url=...,
  api_key=...)`), c'est la façon la plus directe de parler à un serveur
  OpenAI-compatible.
- `pymupdf` (déjà dépendance transitive de `pymupdf4llm`) pour le rendu
  PDF→PNG par page — **pas** `pymupdf4llm` (pas de markdown, pas d'OCR
  applicatif sur ce chemin : NuExtract lit directement les images).
- Doc de référence à consulter avant/pendant l'implémentation :
  https://github.com/numindai/nuextract (format exact du schéma JSON,
  `verbatim-string`, `chat_template_kwargs`) — l'API peut avoir évolué
  depuis la recherche faite pendant ce cadrage, ne pas coder de mémoire
  (règle CLAUDE.md : ce lien fait foi).

## Commands

```bash
uv run python scripts/nuextract_pipeline_eval.py   # rejoue le pipeline NuExtract sur le gold, sortie CSV
```
(nom de script à confirmer en Plan — suit le pattern `scripts/dspy_prompt_tuning.py`)

Tests (inchangé) :
```bash
uv run pytest -v -m "not live"
```

## Project Structure

Nouveaux fichiers uniquement sous `scripts/`/`tests/` — **rien dans `app/`**
(pas de branchement sur le `Protocol` `NerExtractor`/`PdfTextExtractor`
existant, voir "Not Doing" du one-pager) :

```
scripts/nuextract_client.py        → rendu PDF->images (PyMuPDF), appel chat/completions,
                                      parsing JSON -> list[ExtractionResult]
scripts/nuextract_pipeline_eval.py → task callable + réutilisation de gold_matching pour
                                      scorer, sortie CSV (pattern scripts/dspy_prompt_tuning.py)
tests/test_nuextract_client.py     → tests offline (mock du client HTTP), hors réseau
specs/nuextract-pipeline-spike.md  → cette spec
tasks/plan-nuextract-pipeline-spike.md,
tasks/todo-nuextract-pipeline-spike.md → suite (Plan/Tasks)
```

Modifiés :
```
.env.example → ajout NUEXTRACT_BASE_URL, NUEXTRACT_API_KEY (vides par défaut)
```

## Code Style

Mêmes conventions que le reste du repo : scripts impératifs simples sous
`scripts/` (référence la plus proche : `scripts/dspy_prompt_tuning.py` —
script autonome hors `app/`, sortie CSV, réutilise le scoring existant),
pas de nouveau `Protocol` ici (ce pipeline n'est justement pas branché sur
`NerExtractor`). Réutiliser tel quel : `app/tools/type_coercion.py` pour la
coercion typée, `scripts/gold_matching.py` pour le scoring — aucune
réimplémentation.

**Mise à jour post-vérification doc (confirmé contre
https://github.com/numindai/nuextract) :** le "template" NuExtract est un
JSON plat `{nom_du_champ: type}` (types de base : `"verbatim-string"`,
`"string"`, `"integer"`, `"number"`, `"date"`, ... — pas d'objet imbriqué
`{value, evidence}` par champ confirmé dans la doc publique). Simplification
retenue : **un seul type par champ demandé, `"verbatim-string"`, pour
tous les `FieldType`** — exactement ce que demande le cadrage ("pour
l'evidence, il pourra utiliser verbatim-string"), et ça évite de parier sur
une syntaxe de schéma imbriqué non confirmée. La réponse est du JSON pur
(`response.choices[0].message.content`), clé = `field.key`.

Mapping `ExtractionResult` (mêmes conventions que
`app/tools/ner_langextract.py`) :
- `source="nuextract"`
- `value` = le texte `verbatim-string` renvoyé par le modèle pour ce
  champ — texte littéral, comme `chosen.extraction_text` côté LangExtract.
- `typed_value` = **le même texte littéral** (pas de second champ typé
  séparé côté NuExtract) — `type_error` calculé dessus via
  `type_coercion.validate(raw_value, field.type)`, identique au traitement
  qu'un champ LangExtract subirait s'il n'avait pas de `attributes['value']`
  (voir `_typed_value` dans `ner_langextract.py`).
- `page_number`/`text_position` = `None` (pas de grounding en v1, décidé en
  cadrage).

## Testing Strategy

- Offline uniquement pour les tests automatisés (`pytest -m "not live"`) :
  mock de l'appel `openai.chat.completions.create`, vérifie le rendu
  PDF→images, le mapping JSON→`ExtractionResult(source="nuextract")`, et la
  coercion typée réutilisée (`type_coercion.validate`).
- Pas de test `live` automatisé contre le vrai serveur NuExtract (pas de
  garantie de disponibilité en CI, pas de secret partagé) — la vérification
  bout-en-bout et le run gold réel restent **manuels, faits par l'humain**
  (règle CLAUDE.md — ce chantier n'est pas du DSPy, pas d'exception ici).

## Boundaries

- **Toujours faire :** `source="nuextract"` sur chaque `ExtractionResult`
  produit, pour distinguer clairement des runs `"langextract"`/`"mock"`
  existants ; consulter https://github.com/numindai/nuextract avant
  d'écrire le code d'appel API (le format exact du schéma peut avoir
  changé depuis ce cadrage) ; réutiliser
  `gold_matching.classify_field`/`precision_recall_f1` tel quel.
- **Demander d'abord :** toute modification de `app/` (routes, `Protocol`,
  UI) — ce chantier reste un script autonome sous `scripts/` ; toute
  dépendance nouvelle au-delà du SDK `openai` déjà résolu.
- **Ne jamais faire :** lancer le run réel complet sur le dataset gold
  depuis Claude (règle CLAUDE.md — seul l'humain le lance et l'interprète) ;
  committer `NUEXTRACT_API_KEY` ou une URL de serveur privée en clair.

## Success Criteria

- [x] `scripts/nuextract_client.py` rend un PDF en une image PNG par page
      (PyMuPDF), envoie **toutes** les images d'un document en un **seul**
      appel `chat/completions` (pas de découpage), et retourne
      `list[ExtractionResult]` avec `source="nuextract"`, `value`=evidence
      `verbatim-string`, `typed_value` coercée.
      *`render_pdf_pages`/`build_template`/`parse_response`/`extract` —
      7 tests offline, `tests/test_nuextract_client.py`.*
- [x] `scripts/nuextract_pipeline_eval.py` rejoue ce pipeline sur (un
      sous-ensemble du) dataset gold et produit un CSV avec précision/
      recall/F1 par champ + macro — comparable au format déjà produit par
      les runs DSPy existants (`tasks/*.csv`).
      *`run`/`run_document`/`aggregate_scores`/`write_results_csv` —
      8 tests offline, `tests/test_nuextract_pipeline_eval.py`. `--limit`
      ajouté pour valider sur un sous-ensemble avant un run complet.*
- [x] `uv run pytest -v -m "not live"` passe, y compris les nouveaux tests
      offline, sans régression sur la suite existante.
      *286 passed, 1 deselected (`-m live`).*
- [x] Aucune modification de `app/` (`Protocol` `NerExtractor`/
      `PdfTextExtractor` inchangés, aucune route/UI touchée).
      *Fichiers touchés : `scripts/`, `tests/`, `.env.example`, `docs/`,
      `specs/` — rien sous `app/`.*
- [ ] Le run réel sur le dataset gold est déclenché et interprété par
      l'humain, pas par Claude.
      *Bloqué sur la config `NUEXTRACT_BASE_URL` côté humain — script prêt
      (`uv run python scripts/nuextract_pipeline_eval.py --limit 2` pour
      un premier essai réduit).*

## Open Questions

- Nom exact du modèle servi par le serveur vLLM de l'utilisateur (défaut
  code : `numind/NuExtract3`, overridable via l'argument `model` de
  `nuextract_client.extract` — n'affecte pas le reste du pipeline).
- ~~Scorer sur les 14 documents gold en une fois, ou d'abord sur un
  sous-ensemble ?~~ Résolu : `--limit N` sur
  `scripts/nuextract_pipeline_eval.py`.
