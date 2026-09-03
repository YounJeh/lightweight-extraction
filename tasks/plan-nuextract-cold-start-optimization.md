# Implementation Plan: Cold start NuExtract/Modal sous 1 minute

Cadrage : [docs/ideas/nuextract-cold-start-optimization.md](../docs/ideas/nuextract-cold-start-optimization.md).
Branche : `feat/nuextract-pipeline-spike` (suite du spike, pas de nouvelle
branche).

## Overview

Boucle empirique instrumentée : mesurer le cold start actuel, appliquer un
levier, redéployer, remesurer, vérifier l'absence de régression sur le
corpus gold, documenter (gain ou échec), répéter jusqu'à passer sous 1 min
de façon stable ou épuiser les leviers priorisés. Chaque levier = une tâche
courte (config + redeploy + mesure + log), pas une grosse réécriture.

**Autorisation explicite (utilisateur, invocation `/idea-refine`)** :
l'agent peut déployer sur Modal et exécuter le modèle sur les exemples du
corpus gold pour mesurer et vérifier l'absence de régression, pour ce
chantier précis — override scopé de la règle générale `CLAUDE.md`
("Ne fais pas de run de vérification sur le corpus gold"), sur le même
principe que l'exception déjà actée pour DSPy.

## Architecture Decisions

- **Modal GPU memory snapshot + vLLM `--enable-sleep-mode` = levier
  prioritaire** (recherche menée en amont, `/idea-refine`) : Modal publie
  un exemple officiel combinant vLLM + GPU snapshot avec exactement le même
  pattern que notre serveur (`@app.server`, volumes HF/vLLM cache,
  `subprocess.Popen`) — pattern vérifié : `enable_memory_snapshot=True` +
  `experimental_options={"enable_gpu_snapshot": True}` sur le décorateur,
  `@modal.enter(snap=True)` démarre vLLM avec `--enable-sleep-mode`, envoie
  quelques requêtes de warmup, puis `sleep(level=1)` (POST `/sleep?level=1`) ;
  `@modal.enter(snap=False)` réveille via POST `/wake_up`. Gains publiés sur
  des cas similaires : 460s → ~70s (6.5x), 45s → 5s sur un petit modèle —
  cohérent avec notre cible (<1 min depuis ~2-3 min).
  Source : [modal.com/docs/examples/lfm_snapshot](https://modal.com/docs/examples/lfm_snapshot),
  [modal.com/docs/examples/gpu_snapshot](https://modal.com/docs/examples/gpu_snapshot),
  [modal.com/blog/gpu-mem-snapshots](https://modal.com/blog/gpu-mem-snapshots).
- **`--enforce-eager` déjà en place réduit un risque connu du snapshot** :
  la doc Modal signale que `torch.compile` peut faire échouer la création
  du snapshot dans certains cas — non applicable ici, CUDA graphs/compile
  déjà désactivés.
- **Feature alpha, opt-in, GPU non listé explicitement (L4)** — risque
  réel à vérifier en premier (Task 4) : la doc cite a10/a10g/h100 en
  exemple, pas L4 explicitement. Si incompatible, on le découvre vite (une
  tâche isolée) sans avoir construit tout le reste dessus.
- **Snapshot restore : "les gains apparaissent après quelques cold starts
  (typiquement < 5)"** — donc le premier cold start après un déploiement
  reste lent ; la mesure doit distinguer 1er cold start (baseline) vs
  cold starts en régime établi (post-snapshot). Le harness (Task 1) doit
  déclencher et logger plusieurs cycles, pas un seul.
- **Volumes Modal ne rafraîchissent pas le snapshot automatiquement** —
  si le cache HF/vLLM change après la création du snapshot, restore peut
  échouer. À surveiller si on modifie les volumes en cours de route
  (Task 4+).
- **Quantization (AWQ/GPTQ/FP8) rétrogradée** : NuExtract3 n'a **aucun
  checkpoint quantifié officiel** publié par numind (vérifié sur
  [github.com/numindai/nuextract](https://github.com/numindai/nuextract),
  conformément à `CLAUDE.md`) — un seul variant 4B documenté. Quantifier
  soi-même (AutoAWQ/AutoGPTQ) reste possible mais plus risqué (format de
  sortie) et plus long — repoussé en Phase 2/3 contingente, pas en
  priorité 1.
- **Test log dédié** : `docs/nuextract-cold-start-tests.md` (nouveau) —
  table par tentative (levier, config, cold start mesuré sur N runs,
  régression gold, décision). `choix_techniques.md` ne reçoit que la
  décision finale retenue, en une entrée brève, une fois le chantier
  conclu (règle CLAUDE.md : bref, cœur de l'app).
- **Vérification gold allégée, pas le pipeline Langfuse complet** :
  itérer avec `scripts/nuextract_gold_langfuse_eval.py` (qui crée un run
  Langfuse par appel) serait bruyant pour des dizaines d'itérations
  rapides. Le regression-check (Task 2) réutilise directement
  `nuextract_client.extract()` + comparaison aux valeurs de
  `tests/data/dataset_gold_devis.yaml` (18 documents), sans passer par
  Langfuse. Le run Langfuse "officiel" reste réservé au wrap-up (Task 9),
  pour la trace finale.

## Task List

### Phase 0 : Fondation — instrumentation avant tout levier

- [ ] Task 1: Harness de mesure du cold start (déclenchement + mesures
      répétées + log)
- [ ] Task 2: Vérification allégée de non-régression sur le corpus gold
- [ ] Task 3: Scaffold du test log + mesure baseline (config actuelle,
      plusieurs cycles)

### Checkpoint : Phase 0
- [ ] Le harness force un cold start de façon fiable et mesure le temps
      jusqu'à première réponse réussie.
- [ ] La vérification gold tourne sur les 18 documents sans appel Langfuse.
- [ ] `docs/nuextract-cold-start-tests.md` contient une entrée baseline
      avec plusieurs mesures (pas un seul run) — c'est le chiffre à battre.

### Phase 1 : Levier prioritaire — GPU memory snapshot + vLLM sleep mode

- [ ] Task 4: Implémenter `enable_memory_snapshot` + `--enable-sleep-mode`
      + cycle `snap=True`/`snap=False`, déployer, mesurer, vérifier
      régression, logger.

### Checkpoint : Phase 1
- [ ] Décision documentée : cold start en régime établi < 1 min de façon
      stable (plusieurs cycles, pas un coup de chance) ET pas de
      régression sur le corpus gold → **si oui, chantier terminé, passer
      au wrap-up (Phase 3)**.
- [ ] Si le GPU snapshot est incompatible (L4 non supporté, échec de
      restore) ou insuffisant seul → passer en Phase 2, détailler les
      tâches suivantes à ce moment (pas pré-écrites ici, cf. Risks).

### Phase 2 (contingente — détaillée uniquement si Phase 1 insuffisante)

Non pré-découpée en tâches ici : sa nécessité dépend du résultat de la
Phase 1. Pistes dans l'ordre de priorité si besoin, à transformer en
tâches concrètes (même gabarit que Task 4) au moment du checkpoint :
1. Réglages vLLM (`--gpu-memory-utilization`, `--kv-cache-dtype fp8`).
2. Image plus fine (dépendances minimales, moins de temps de pull/import).
3. Comparaison GPU (L4 vs A10G vs A100, coût comparable).
4. Quantization self-service (AutoAWQ/AutoGPTQ) si les leviers précédents
   ne suffisent pas — risque de régression le plus élevé, testé en
   dernier.
5. Changement de moteur d'inférence (sortir de vLLM) — dernier recours
   (voir "Not Doing" du cadrage), non détaillé tant que non nécessaire.

### Phase 3 : Wrap-up

- [ ] Task 5: Finaliser la config serveur retenue (réconcilier l'édit
      local non commité `scaledown_window=600` avec le résultat obtenu).
- [ ] Task 6: Entrée brève dans `choix_techniques.md` (décision finale
      uniquement, lien vers le test log).
- [ ] Task 7: Finaliser `docs/nuextract-cold-start-tests.md` comme
      artefact d'entretien (table récapitulative + narratif court).

### Checkpoint : Complete
- [ ] Cold start < 1 min stable, sans régression gold, documenté de bout
      en bout.
- [ ] `uv run pytest -v -m "not live"` — aucune régression sur la suite
      existante.
- [ ] Proposer `/code-review-and-quality` puis une PR (règle CLAUDE.md :
      chantier de feature terminé sur cette branche).

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| GPU snapshot alpha ne supporte pas/mal le GPU L4 (non listé explicitement dans la doc Modal) | High — invalide le levier prioritaire | Task 4 teste ça en tout premier, isolé ; échec documenté rapidement, bascule Phase 2 sans avoir tout misé dessus |
| Le snapshot ne rafraîchit pas si les volumes (cache HF/vLLM) changent en cours de route | Medium — restore peut échouer silencieusement après une modif de volume | Noter explicitement dans le test log à chaque changement de volume ; re-snapshot (redeploy) si besoin |
| Mesurer un seul cold start "chanceux" et le prendre pour la nouvelle baseline | High — invalide toute la boucle de décision | Task 1 force plusieurs cycles par mesure (jamais un seul run), le doc Modal indique lui-même que les gains n'apparaissent qu'après ~5 cold starts |
| Vérification gold allégée (Task 2) passe à côté d'une régression que le pipeline Langfuse complet aurait détectée | Medium | Le run Langfuse officiel (Task 9/wrap-up) reste fait avant la PR, comme filet final |
| Itérer trop longtemps sur des leviers à faible rendement sans jamais passer sous 1 min | Medium | Checkpoint explicite après Phase 1 (le levier le plus prometteur) ; Phase 2 n'est détaillée qu'au besoin, pas pré-planifiée en détail |

## Open Questions

- Le GPU snapshot Modal fonctionne-t-il avec un GPU L4 ? Réponse attendue
  dès Task 4 (pas de doc confirmant explicitement L4 dans la liste
  supportée).
- `--enable-sleep-mode` de vLLM est-il compatible avec `--enforce-eager`
  déjà en place ? À vérifier au premier déploiement de Task 4 (pas de
  conflit documenté trouvé, mais pas explicitement confirmé compatible
  non plus).
