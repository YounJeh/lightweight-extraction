# Tasks: Cold start NuExtract/Modal sous 1 minute

Plan : [tasks/plan-nuextract-cold-start-optimization.md](plan-nuextract-cold-start-optimization.md).

Phase 2 (réglages vLLM, image, GPU alternatif, quantization, changement de
moteur) n'est volontairement pas détaillée ici — elle dépend du résultat
du Checkpoint Phase 1 (Task 4). Ses tâches seront écrites, avec le même
gabarit, uniquement si ce checkpoint le déclenche.

## Task 1: Harness de mesure du cold start

**Description:** Nouveau script `scripts/nuextract_cold_start_bench.py` :
force un cold start (redéploiement du serveur Modal, ou attente confirmée
de `scaledown_window`), puis envoie une requête réelle (un PDF gold, peu
importe lequel) via `nuextract_client.extract()` en mesurant le temps
jusqu'à la première réponse réussie. Répète sur N cycles (N configurable,
défaut 5 — cohérent avec "les gains n'apparaissent qu'après ~5 cold
starts" observé côté Modal). Chaque mesure ajoute une ligne structurée
(JSON ou CSV) dans `docs/nuextract-cold-start-tests.md` ou un fichier de
données séparé référencé depuis ce doc — au choix pendant l'implémentation,
mais la donnée brute (pas juste une moyenne) doit être conservée.

**Acceptance criteria:**
- [x] Le script force un cold start vérifiable (ex: `modal app stop` /
      redeploy, ou vérification explicite que le conteneur précédent est
      bien descendu avant de mesurer) — pas une mesure sur un conteneur
      déjà chaud par accident.
- [x] Mesure le temps écoulé entre la 1ère requête envoyée et la 1ère
      réponse HTTP 200 reçue (les retries internes de `extract()` comptent
      dans ce temps, cohérent avec `cold_start_seconds` déjà défini côté
      Langfuse eval).
- [x] Répète sur plusieurs cycles consécutifs, log individuel de chaque
      cycle (pas seulement une moyenne finale).

**Verification:**
- [x] Exécution réelle par l'agent (autorisation explicite de ce
      chantier) sur au moins 2 cycles, résultat visible dans le log.
- [x] Pas de test offline nécessaire pour la partie "force un cold start
      réel" (dépend de Modal) ; une fonction pure de calcul de durée peut
      être testée séparément si extraite.

**Dependencies:** None

**Files likely touched:**
- `scripts/nuextract_cold_start_bench.py` (nouveau)
- `docs/nuextract-cold-start-tests.md` (nouveau, scaffold minimal)

**Estimated scope:** S

---

## Task 2: Vérification allégée de non-régression sur le corpus gold

**Description:** Fonction réutilisable (dans le même script ou un module
partagé) qui appelle `nuextract_client.extract()` sur les 18 documents de
`tests/data/dataset_gold_devis.yaml` (dossier `data_test/`) et compare les
valeurs extraites aux valeurs gold annotées — réutilise si possible la
logique de matching déjà existante (`scripts/gold_matching.py`) plutôt que
réinventer une comparaison. Sortie : nombre de champs corrects/incorrects
par document + total, pas un score P/R/F1 complet (ce n'est pas
`gold_dataset_eval.py`, juste un filet de non-régression rapide entre deux
configs serveur).

**Acceptance criteria:**
- [x] Tourne sur les 18 documents gold sans créer de run Langfuse.
- [x] Réutilise `gold_matching` (import, pas de duplication de la logique
      de comparaison de valeurs).
- [x] Sortie exploitable pour comparer deux configs (avant/après un
      changement de levier) — un diff simple suffit, pas un dashboard.

**Verification:**
- [x] Exécution réelle par l'agent sur la config baseline actuelle
      (autorisation explicite de ce chantier), résultat archivé comme
      référence de non-régression pour les leviers suivants.

**Dependencies:** None (peut démarrer en parallèle de Task 1)

**Files likely touched:**
- `scripts/nuextract_cold_start_bench.py` (ou nouveau module partagé)

**Estimated scope:** S

---

## Task 3: Scaffold du test log + mesure baseline

**Description:** Créer `docs/nuextract-cold-start-tests.md` avec une table
(colonnes : date, levier testé, config/diff, cold start mesuré — min/
médiane/max sur N runs —, résultat régression gold, décision
gardé/rejeté, notes). Première ligne : mesure de la config **actuelle**
de `scripts/modal_nuextract_server.py` (déjà optimisée : eager mode,
cache vLLM, prefetch) avec Task 1 + Task 2 — c'est la baseline à battre,
pas la config vanilla.

**Acceptance criteria:**
- [x] Table avec au moins une ligne "baseline (config actuelle)" remplie
      avec de vraies mesures (pas des valeurs placeholder).
- [x] Format de table stable, réutilisable pour chaque tâche suivante
      (Task 4+) sans réorganisation.

**Verification:**
- [x] Lecture manuelle du fichier — cohérence avec les sorties brutes de
      Task 1/Task 2.

**Dependencies:** Task 1, Task 2

**Files likely touched:**
- `docs/nuextract-cold-start-tests.md`

**Estimated scope:** XS

---

## Checkpoint : Phase 0

- [x] Harness fiable (Task 1), regression-check fonctionnel (Task 2),
      baseline documentée avec plusieurs mesures (Task 3).
- [x] Chiffre baseline clair : cold start (médiane sur N runs) de la
      config actuelle — c'est ce chiffre que le Task 4 doit faire passer
      sous 1 min.

---

## Task 4: GPU memory snapshot + vLLM `--enable-sleep-mode`

**Description:** Modifier `scripts/modal_nuextract_server.py` :
- Ajouter `enable_memory_snapshot=True,
  experimental_options={"enable_gpu_snapshot": True}` au décorateur
  `@app.server(...)`.
- Ajouter `--enable-sleep-mode` à la commande `vllm serve`.
- Séparer `start_server` en `@modal.enter(snap=True)` (démarre vLLM,
  attend qu'il soit prêt, envoie 1-2 requêtes de warmup réelles, puis met
  le serveur en veille — `POST /sleep?level=1` ou équivalent CLI/API
  exposé par vLLM) et `@modal.enter(snap=False)` (réveille le serveur —
  `POST /wake_up`).
- Déployer, mesurer avec Task 1 sur au moins 5 cycles consécutifs (le gain
  n'apparaît qu'après quelques cold starts d'après la doc Modal — logger
  chaque cycle séparément, y compris les premiers, moins bons).
- Vérifier la non-régression avec Task 2, comparer à la baseline Task 3.
- Logger le résultat dans `docs/nuextract-cold-start-tests.md`, succès ou
  échec (y compris si le GPU L4 s'avère incompatible avec le snapshot —
  documenter l'erreur exacte, pas juste "ça n'a pas marché").

**Acceptance criteria:**
- [x] Déploiement réussi avec la nouvelle config (ou échec documenté avec
      le message d'erreur exact si L4 incompatible).
- [x] Au moins 5 cycles de cold start mesurés en régime établi (pas
      seulement le tout premier après déploiement).
- [x] Résultat de non-régression gold (Task 2) comparé à la baseline.
- [x] Ligne(s) ajoutée(s) dans `docs/nuextract-cold-start-tests.md` avec
      la décision (gardé/rejeté) et pourquoi.

**Verification:**
- [x] Exécution réelle par l'agent (déploiement Modal + mesures + check
      gold), autorisation explicite de ce chantier.
- [x] `uv run pytest -v -m "not live"` — aucune régression sur la suite
      offline existante (ce changement touche un script de déploiement,
      pas de code applicatif testé unitairement, mais vérifier quand
      même qu'aucun import cassé).

**Dependencies:** Task 3 (baseline nécessaire pour comparer)

**Files likely touched:**
- `scripts/modal_nuextract_server.py`
- `docs/nuextract-cold-start-tests.md`

**Estimated scope:** M (config serveur + cycle de déploiements/mesures
réels, pas juste un edit de fichier)

---

## Checkpoint : Phase 1

**Décision initiale (2026-09-02, cycles rapprochés)** : résultat
**majoritaire, pas strictement stable** — 5/6 cycles en régime établi sous
60s (29-56s), 1/6 outlier à 346.3s, root cause identifiée via
`modal app logs` comme un ralentissement côté infrastructure de restore
Modal elle-même. Pas de régression gold.

**CORRIGÉ le même jour, suite à un signalement utilisateur** (cold start
toujours > 3 min via `nuextract_gold_langfuse_eval.py`) : re-testé en
usage réel espacé (pas les cycles rapprochés du harness) — 0/3
restaurations rapides sur 3 tentatives réalistes (1 reconstruction
attendue au 1er usage, 1 reconstruction inattendue ~13 min plus tard, 1
restauration réussie mais lente ~2m46). **Le levier GPU snapshot est
retiré** — la décision "majoritaire" ci-dessus reposait sur une méthodo de
test (cycles rapprochés via `container stop`) qui ne représente pas
l'usage réel. Voir `docs/nuextract-cold-start-tests.md` pour le détail
complet, y compris deux leviers de remplacement testés ensuite
(`--kv-cache-memory`, `TRITON_CACHE_DIR`) — aucun n'a encore résolu le
problème. **Chantier rouvert, pas classé "Phase 2 inutile" comme prévu
initialement.**

- [x] Décision explicite et documentée (ci-dessus + test log), y compris
      la correction.
- [x] Config gardée comme nouvelle base pour la Phase 3 (wrap-up) —
      gain net majoritaire, pas de régression, pas pire que baseline dans
      le pire cas. Phase 2 non nécessaire dans l'immédiat (voir ci-dessus).

---

## Task 5: Finaliser la config serveur retenue

**Description:** Une fois le levier gagnant identifié (Task 4 ou une
tâche de Phase 2), nettoyer `scripts/modal_nuextract_server.py` de tout
essai non retenu. Réconcilier l'édit local non commité
(`scaledown_window=600`, actuellement non commité sur cette branche) avec
le résultat : si le cold start réel est maintenant < 1 min et stable, un
`scaledown_window` court redevient défendable (le coût GPU idle prime sur
la lenteur de redémarrage, qui n'est plus un problème) — décision à
documenter, pas à trancher ici à l'avance.

**Acceptance criteria:**
- [x] `scripts/modal_nuextract_server.py` reflète uniquement la config
      finale retenue, commentée (pourquoi ce choix, pas les essais
      écartés — ça, c'est dans le test log).
- [x] `scaledown_window` a une valeur justifiée par le résultat mesuré,
      pas un reliquat de debug.

**Verification:**
- [x] Relecture manuelle du diff final vs. HEAD de cette branche.

**Dependencies:** Task 4 (ou tâche(s) de Phase 2 si déclenchées)

**Files likely touched:**
- `scripts/modal_nuextract_server.py`

**Estimated scope:** XS

---

## Task 6: Entrée brève dans `choix_techniques.md`

**Description:** Ajouter une entrée courte (format existant du fichier :
Contexte → Décision → Alternatives écartées) documentant uniquement la
décision finale retenue pour le cold start — pas le détail des essais
(ça reste dans `docs/nuextract-cold-start-tests.md`, lien inclus).

**Acceptance criteria:**
- [x] Entrée brève, même format que les entrées existantes du fichier.
- [x] Lien vers `docs/nuextract-cold-start-tests.md` pour le détail complet.

**Verification:**
- [x] Relecture manuelle — cohérence avec la règle CLAUDE.md ("très bref
      et synthétique", "uniquement ce qui touche au cœur de l'application").

**Dependencies:** Task 5

**Files likely touched:**
- `choix_techniques.md`

**Estimated scope:** XS

---

## Task 7: Finaliser le test log comme artefact d'entretien

**Description:** Relire `docs/nuextract-cold-start-tests.md` de bout en
bout, ajouter un court résumé en tête (baseline → décision finale, gains
et échecs en une table lisible) pensé pour être montré tel quel en
entretien — pas de réécriture du détail déjà loggé au fil de l'eau, juste
un chapeau de synthèse.

**Acceptance criteria:**
- [x] Résumé en tête du fichier : baseline, cold start final, % de gain,
      leviers gardés vs rejetés en une phrase chacun.
- [x] Table détaillée (déjà remplie au fil des tâches précédentes)
      inchangée dans le fond, juste vérifiée pour la cohérence.

**Verification:**
- [x] Relecture manuelle.

**Dependencies:** Task 6

**Files likely touched:**
- `docs/nuextract-cold-start-tests.md`

**Estimated scope:** XS

---

## Checkpoint final

**MIS À JOUR (2026-09-03)** : suite au signalement utilisateur (cold start
toujours > 3 min), le vrai goulot a été isolé (JIT Triton, ~100s+) et
corrigé en le déplaçant du runtime vers le build de l'image. Gain réel et
vérifié : ~288s → ~186s (médiane, 6 cycles au total, 2 vérifications gold
indépendantes sans régression). **Cible < 1 min toujours non atteinte** —
le reste est décomposé précisément (ordonnancement Modal + démarrage du
2e process vLLM, ~93s sur ~153s, aucun flag connu ne les élimine à ce
stade) dans `docs/nuextract-cold-start-tests.md`.

- [x] Cold start réduit de façon mesurée et vérifiée (~35%, 288s → 186s),
      stable sur plusieurs cycles à intervalle réaliste (pas seulement en
      cycles rapprochés). **< 1 min non atteint** — décomposition précise
      du temps restant documentée, aucune régression gold (2 vérifications
      indépendantes, F1 identique à la baseline).
- [x] `choix_techniques.md` reflète l'état réel (gain partiel, cible non
      atteinte), pas une fausse victoire ni un abandon prématuré.
- [x] `uv run pytest -v -m "not live"` passe intégralement (302 passed,
      1 deselected).
- [ ] Proposer `/code-review-and-quality` puis une PR — **prématuré tant
      que le chantier n'est pas résolu ou explicitement mis en pause avec
      l'accord de l'utilisateur.**
