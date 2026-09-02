# Choix techniques

Décisions techniques hors périmètre des specs (`specs/`) : arbitrages,
contournements, compromis. Format : contexte → décision → alternatives
écartées.

---

## Déduplication des résultats d'extraction (arbitrage LLM)

**Contexte :** LangExtract chunk le texte (~1000 car.) et interroge chaque
champ sur chaque chunk → un même champ ressort plusieurs fois, avec des
valeurs différentes. Deux causes : chunks sans la valeur (extraction
fantôme, `char_interval=None`) et chunks avec la valeur à plusieurs
endroits du document (extractions groundées mais divergentes). Le chunking
se fait par phrase, sans overlap entre chunks — comportement par défaut de
LangExtract (`langextract/chunking.py`), non paramétré côté app.

**Décision** (`app/tools/ner_langextract.py`) :
- extractions non groundées / vides → ignorées ;
- 0 candidat → champ absent ; 1 candidat → accepté ; N identiques
  (normalisés) → 1ère occurrence ; N distincts → **arbitrage par un 2e
  appel `langextract.extract()`** (le modèle choisit parmi les candidats),
  repli sur la 1ère occurrence si la réponse ne matche rien.

**Écarté :** toujours garder la 1ère occurrence (perd de l'info) ·
concaténer les valeurs (contraire au besoin d'une valeur unique) · second
SDK LLM dédié (inutile, un seul point d'accès LLM suffit) · augmenter
`max_char_buffer` (traite le symptôme, pas les faux positifs).

**Réf :** [specs/dedupe-extraction-results.md](specs/dedupe-extraction-results.md) ·
[tests/test_ner_langextract_dedupe.py](tests/test_ner_langextract_dedupe.py)

---

## OCR des pages scannées (PyMuPDF4LLM + RapidOCR)

**Contexte :** le chemin texte léger de PyMuPDF4LLM
(`use_layout(False)`) ne fait aucun OCR — une page photocopiée/scannée sans
couche texte (ex. page 12 de `104__DEVIS_25110230_VERSION_A03.pdf`, une
photocopie de CGV) ne produisait que le texte accessoire de la page (11
caractères), rien d'exploitable pour le NER.

**Décision** (`app/tools/pdf_pymupdf4llm.py`) : réactivation du moteur
layout (`use_layout(True)`), OCR géré nativement par PyMuPDF4LLM en mode
"si nécessaire" (`use_ocr` par défaut). Backend RapidOCR (`rapidocr`, pas
`rapidocr-onnxruntime`, préféré nativement par PyMuPDF4LLM quand les deux
sont installés) : détection *et* reconnaissance faites par RapidOCR, aucune
dépendance Tesseract sur ce chemin. `ocr_language="fra"` passé en dur
(pas de variable d'environnement) — décision utilisateur.

**Correction (Task 2) — le mode "si nécessaire" n'est pas aussi ciblé
qu'espéré :** vérifié avec `make_ocr_decision`/`analyze_page` sur le PDF de
test réel, `needs_ocr=True` sur les **12 pages** du document, pas seulement
la page 12 photocopiée — de petites images (logo/en-tête, `img_area` ~2-12%)
et graphiques vectoriels présents sur chaque page suffisent à déclencher la
décision. Le texte natif n'est jamais écrasé (l'OCR ne traite que les zones
sans texte lisible, `exec_ocr_full` exclut explicitement les spans de "bon"
texte avant de construire l'image à OCRiser), mais RapidOCR tourne bel et
bien sur la quasi-totalité des pages de ce document (~2 min sur ce PDF de 12
pages), pas juste sur la page scannée. Décision utilisateur (Task 2) :
garder ce comportement natif de PyMuPDF4LLM tel quel plutôt que d'ajouter un
filtre maison (seuil de texte natif) — le signal `pages_ocr` tracé côté
Langfuse (Task 3-4) reflétera donc fidèlement cette réalité plutôt qu'une
distinction "propre" natif/OCR par page.

**Écarts découverts en implémentation :**
- `rapidocr` tire `opencv-python` (non headless), qui exige `libGL.so.1`
  absent des environnements serveur/CI sans X11 → ajout de
  `opencv-python-headless` comme dépendance directe pour forcer un `cv2`
  sans cette dépendance système (les deux packages installent au même
  chemin ; l'ordre alphabétique du lock fait gagner la variante headless,
  vérifié stable sur `uv sync` à froid **en local uniquement — voir incident
  ci-dessous, ce pari ne tient pas sur le buildpack Cloud Run**).
- `ocr_language="fra"` est en réalité un **no-op** avec RapidOCR : ce kwarg
  n'est utilisé que sur le chemin Tesseract "detection-only" de PyMuPDF4LLM ;
  RapidOCR utilise son propre modèle de reconnaissance multilingue sans
  sélecteur de langue dans cette intégration. Gardé quand même (intention
  explicite, filet si le chemin Tesseract est utilisé un jour).
- Réactiver le moteur layout change le format des séparateurs de page
  (`--- end of page=N ---` 0-indexé → `--- end of page.page_number=N ---`
  1-indexé) — `PAGE_SEPARATOR_RE` mis à jour ; sans impact sur la logique de
  comptage de page dans `LangExtractNerExtractor._locate`.

**Écarté :** OCR via vision-LLM (Gemini) — coût par appel supplémentaire,
point d'accès LLM en plus · Tesseract/PaddleOCR — dépendance système binaire
(Tesseract) ou moins mature côté PyMuPDF4LLM · `ocr_language` configurable
via `.env` — pas de besoin multi-langue identifié pour l'instant.

---

## Incident : `ImportError: libxcb.so.1` en production (Cloud Run)

**Contexte :** premier déploiement avec l'OCR (voir section précédente)
cassé en production dès le premier upload d'un PDF réel
(`data_test/26-0743 Tournan V1 2026-03-20.pdf`) — `500 Internal Server
Error`, logs Cloud Run :
`ImportError: libxcb.so.1: cannot open shared object file`, remontant à
`import cv2` déclenché par `rapidocr`. Le pari sur l'ordre d'installation
(`opencv-python-headless` gagnant `opencv-python` via l'ordre alphabétique
du lock, vérifié stable en local avec `uv sync`) ne tient pas sur le build
Cloud Run source-based (buildpacks) — probablement un mécanisme
d'installation différent (export vers `requirements.txt` + `pip install`,
sans garantie d'ordre alphabétique), qui fait gagner la variante GUI
(`opencv-python`, dépend de `libGL`/`libxcb`, absents d'un environnement
serveur) plutôt que la variante headless.

**Décision :** passage à un `Dockerfile` explicite à la racine (déjà
anticipé comme repli dans `specs/deploy-cloud-run.md`) plutôt que de
continuer à parier sur l'ordre d'installation du buildpack. Après
`uv sync --frozen`, désinstallation **des deux** variantes puis
réinstallation de la seule `opencv-python-headless` — désinstaller
uniquement `opencv-python` ne suffit pas : les deux paquets installent aux
mêmes chemins (`cv2/`), donc le `RECORD` de `opencv-python` peut lister des
fichiers que `opencv-python-headless` a effectivement écrits en dernier ; le
désinstaller seul risquerait de supprimer les fichiers headless réellement
utilisés. Séquence validée dans un environnement virtuel jetable avant
d'écrire le `Dockerfile` (`uv pip uninstall opencv-python
opencv-python-headless && uv pip install opencv-python-headless`, `import
cv2` propre après coup). Confirmé via `ldd` que `opencv-python-headless`
n'a aucune dépendance système au-delà de la glibc de base (toutes ses libs
tierces — `libavif`, `libpng`, `libopenblas`, etc. — sont embarquées dans le
wheel) : `python:3.13-slim` suffit, aucun paquet système supplémentaire
nécessaire.

**Écarté :** continuer à parier sur l'ordre d'installation buildpack (déjà
prouvé peu fiable) · changer de backend OCR pour éviter la dépendance
`opencv-python` de `rapidocr` (remise en cause plus large, hors scope d'un
correctif) · désinstaller uniquement `opencv-python` sans réinstaller
`opencv-python-headless` à neuf (risque de supprimer les fichiers headless
réellement utilisés, cf. ci-dessus).

**Round 2 — même erreur après le premier correctif :** le premier
`Dockerfile` (`CMD ["uv", "run", "python", "-m", "app.main"]`) n'a pas
suffi — logs Cloud Run : `import cv2` replante avec le même
`ImportError: libxcb.so.1`. Cause : `uv run` **resynchronise
l'environnement sur `uv.lock` à chaque démarrage du conteneur** (pas juste
au build) — `uv.lock` déclare toujours `opencv-python` (dépendance
transitive de `rapidocr`, jamais retirée du lock, seulement désinstallée
manuellement du `.venv`), donc `uv run` la réinstalle silencieusement à
chaque instance/redémarrage, annulant le nettoyage fait à l'étape `RUN`
précédente. Confirmé en local (venv jetable) : `uv run` sans flag
réinstalle bien `opencv-python` ("Installed 6 packages") ; `uv run
--no-sync` ne touche à rien. Fix : `CMD ["uv", "run", "--no-sync",
"python", "-m", "app.main"]`.

**Effet de bord local, observé ensuite — `uv run` (sans `--no-sync`) peut
casser `cv2` dans ce `.venv` :** le même mécanisme touche le poste de dev,
pas seulement Cloud Run — `uv run python -m app.main` lancé normalement
(README) a réinstallé `opencv-python` et fait planter un upload réel avec
la même `ImportError` (`libGL.so.1` cette fois, variante locale de
`libxcb.so.1`).

**Round 3 — le vrai correctif, pas juste un contournement :** l'hypothèse
"aucun fix `pyproject.toml` propre possible" (notée plus haut) était
fausse — `uv` expose `[tool.uv] override-dependencies`, qui accepte un
marqueur d'environnement. Avec
`override-dependencies = ["opencv-python; python_version<'0'"]` (marqueur
toujours faux), `opencv-python` n'est **jamais résolu du tout**, quelle que
soit la dépendance qui le demande — vérifié dans `uv.lock` (aucune entrée
`opencv-python`, seulement `-headless`) et en réel (`uv run` répété sans
`--no-sync` reste stable). Élimine le besoin de coexistence/pari sur
l'ordre d'installation à la racine, pas seulement au niveau du `Dockerfile`
ou du poste de dev. `CMD ["uv", "run", "--no-sync", ...]` du `Dockerfile`
n'est donc plus nécessaire à la correction (gardé tel quel comme
optimisation de démarrage — évite une vérification de sync réseau à chaque
instance).

**Réf :** [Dockerfile](Dockerfile) · [.dockerignore](.dockerignore) ·
[specs/deploy-cloud-run.md](specs/deploy-cloud-run.md) ·
[pyproject.toml](pyproject.toml)

**Réf :** [docs/ideas/pdf-extraction-ocr-tracing.md](docs/ideas/pdf-extraction-ocr-tracing.md) ·
[tasks/plan-pdf-ocr-tracing.md](tasks/plan-pdf-ocr-tracing.md) ·
[tests/test_pdf_pymupdf4llm.py](tests/test_pdf_pymupdf4llm.py)

---

## Bug connu : arbitrage LLM en échec sur certains documents

**Contexte :** la CI d'évaluation sur le dataset gold
(`scripts/gold_dataset_eval.py`) a révélé, sur un run réel,
`ValueError: Source tokens and extraction tokens cannot be empty.` pendant
l'arbitrage LLM (`_arbitrate`, voir section "Déduplication" ci-dessus) sur
`104__DEVIS_25110230_VERSION_A03.pdf` — déjà connu pour ses soucis d'OCR
(section OCR ci-dessus). Cause probable : un des candidats en conflit a un
texte source vide/non groundé après OCR, ce que le second appel
`langextract.extract()` ne tolère pas.

**Décision :** non corrigé dans ce chantier (hors scope CI) — documenté ici
pour qu'un futur correctif touchant `app/tools/ner_langextract.py` ait le
contexte. Le pipeline ne plante pas silencieusement : l'échec remonte
(exception), la CI l'isole sans bloquer les autres documents.

**Réf :** [specs/ci-eval-gold-dataset.md](specs/ci-eval-gold-dataset.md) ·
[tasks/todo-ci-eval-gold-dataset.md](tasks/todo-ci-eval-gold-dataset.md)

---

## Latence OCR : dpi réduit + seuil de saut sur img_area

**Contexte :** l'OCR se déclenchait sur quasi toutes les pages de documents
réels à cause de logos d'en-tête/pied de page (section OCR ci-dessus),
rendant l'extraction lente (jusqu'à ~2 min/document) sans gain réel — le
logo n'apporte rien à l'extraction NER.

**Décision** (`app/tools/pdf_pymupdf4llm.py`) : `ocr_dpi=72` (au lieu du
défaut 150) et saut d'OCR pour toute page dont `img_area < 0.05` (logo,
pas un scan). Les deux validés ensemble sur les 13 documents du dataset
gold (`scripts/validate_ocr_tuning.py`, script autonome sans appel LLM —
présence des valeurs gold dans le texte OCR brut) : **~77% de temps en
moins, 0 régression** sur les 53 valeurs gold testées.

**Écarté :** seuils `img_area` plus agressifs (0.10, 0.20 — gain marginal
au-delà de 0.05) · seuil basé sur la longueur du texte natif plutôt que
`img_area` (la distribution ne sépare proprement ni sur l'un ni sur
l'autre pris seul, mais `img_area` réutilise directement le signal déjà
calculé par PyMuPDF4LLM) · relancer le pipeline NER complet dans la
validation (coût réel, variance du LLM comme facteur confondant).

**Correctif (texte vectorisé) :** un document réel avec du texte converti en
contours vectoriels à l'export CAO (glyphes = formes non rectangulaires, pas
de couche texte) a `img_area` quasi nul mais un `vec_norects` élevé — le
seuil `img_area < 0.05` seul l'écrasait à tort alors que PyMuPDF4LLM avait
déjà correctement détecté `needs_ocr=True` dessus (`vec_norects` élevé).
Condition de saut désormais `img_area < 0.05 ET vec_norects == 0` — ne
change rien au cas logo (vec_norects reste nul), débloque le cas texte
vectorisé. Non revalidé sur le corpus gold à ce stade (changement
strictement plus permissif : ne peut que déclencher l'OCR dans plus de cas,
jamais en retirer).

**Réf :** [docs/ideas/validation-optimisation-ocr.md](docs/ideas/validation-optimisation-ocr.md) ·
[scripts/validate_ocr_tuning.py](scripts/validate_ocr_tuning.py) ·
[tasks/plan-vector-text-ocr-fallback.md](tasks/plan-vector-text-ocr-fallback.md)

---

## Export vers le gold dataset : réutilisation du mapping title→key existant

**Contexte :** exporter une extraction validée vers
`tests/data/dataset_gold_devis.yaml` exige `Field.key` (slug machine), mais
`ExtractionResult` ne porte que `field_title` (libellé humain, pas garanti
unique en base).

**Décision :** résolution via `{field.title: field.key for field in
field_repo.list_all()}`, calculée à la volée côté route
(`app/routes/extraction.py`) — même pattern déjà en place dans
`scripts/gold_dataset_eval.py` pour le même besoin. Pas de nouvelle colonne
`field_key` sur `extraction_results` : la collision de `title` reste un
risque déjà accepté ailleurs dans le code, pas aggravé ici.

Un champ sans candidat groundé (`ner_langextract.py`) produit désormais une
ligne à `value=""` plutôt qu'une absence silencieuse — nécessaire pour
pouvoir valider "non détecté" comme correct. `value` reste `TEXT NOT NULL`
en base (`gold_matching._is_present` traite déjà `""` comme absent), donc
aucune migration de schéma.

**Écarté :** colonne `field_key` dédiée sur `extraction_results` (migration
évitable) · valeur `NULL` en base pour "non détecté" (aurait nécessité une
migration de contrainte, SQLite ne le permet pas via `ALTER TABLE`).

**Réf :** [tasks/plan-gold-export-from-extraction.md](tasks/plan-gold-export-from-extraction.md) ·
[app/gold_export.py](app/gold_export.py)

---

## Cold start serveur NuExtract (Modal) : GPU memory snapshot + sleep mode vLLM

**Contexte :** cold start du serveur Modal (scale-to-zero) mesuré à
~4,7-5,3 min (baseline instrumentée). Cible : sous 1 min.

**Décision** (`scripts/modal_nuextract_server.py`) : GPU memory snapshot
Modal (alpha, `enable_memory_snapshot` + `experimental_options`) combiné
au sleep mode vLLM (`--enable-sleep-mode`) — le serveur se met en veille
avant le snapshot, se réveille (`/wake_up`) au cold start suivant au lieu
de rejouer tout le chargement. Mesuré en réel sur 9 cycles : 5/6 cycles en
régime établi sous 60s (29-56s), 1/6 outlier à 346s dont la cause,
identifiée via les logs Modal, est le mécanisme de restore lui-même (pas
notre config) — pire cas mesuré (450s) resté dans le budget de retry
client déjà existant, aucune régression sur le corpus gold (F1 0.711 vs
0.696 baseline).

**Écarté :** quantization (aucun checkpoint officiel NuExtract3 publié par
numind) · changement de moteur d'inférence (vLLM → autre) · compter sur un
`scaledown_window` long pour masquer le cold start plutôt que le réduire.

**Réf :** [docs/ideas/nuextract-cold-start-optimization.md](docs/ideas/nuextract-cold-start-optimization.md) ·
[tasks/plan-nuextract-cold-start-optimization.md](tasks/plan-nuextract-cold-start-optimization.md) ·
[docs/nuextract-cold-start-tests.md](docs/nuextract-cold-start-tests.md)
