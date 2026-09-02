# Faire descendre le cold start NuExtract/Modal sous 1 minute

## Problem Statement

Comment faire tomber le cold start du serveur NuExtract (Modal + vLLM,
GPU à la demande, scale-to-zero) sous 1 minute de façon reproductible —
sans se reposer sur un `scaledown_window` long pour masquer le problème
— en documentant chaque option testée (gain ou échec) comme trace
d'entretien ?

**Baseline actuelle** : ~2-3 min observés au départ, mesurés comme
**plus variables en réel** — un run a épuisé 8 retries (~155s) en 503
persistant avant de réussir au run suivant en seulement 3 retries
(`scripts/nuextract_client.py:31-40`). Déjà appliqué sur cette branche :
`--enforce-eager`, cache vLLM persistant, `--safetensors-load-strategy
prefetch`, `--max-num-seqs 8` (`scripts/modal_nuextract_server.py`) —
donc la baseline à battre n'est *pas* la config vanilla, déjà un premier
palier d'optimisation.

## Recommended Direction

Boucle empirique **mesurer → appliquer un levier → redéployer → mesurer
→ garder ou rejeter → documenter**, répétée jusqu'à passer sous 1 min ou
épuiser les leviers identifiés, dans cet ordre de priorité :

1. **Instrumenter d'abord** (`@modal.enter()` timestampé par étape :
   pull image → import → init CUDA → lecture poids → transfert HBM →
   profiling vLLM → prêt) — sans ça, les leviers suivants sont appliqués
   à l'aveugle.
2. **Modal GPU memory snapshot (beta)** — le levier le plus adapté au
   problème (restaure un état GPU déjà initialisé au lieu de rejouer
   tout le chargement). Priorité 1 car gain potentiel le plus important
   pour un seul changement.
3. **Réduire le payload** — quantization (AWQ/GPTQ/FP8) si des poids
   NuExtract3 existent ou peuvent être produits sans casser le format de
   sortie JSON ; réglages vLLM (`--gpu-memory-utilization`,
   `--kv-cache-dtype`) ; image plus fine ; comparaison GPU (L4 vs A10G
   vs A100) si coût comparable.
4. **Changer de moteur d'inférence** (sortir de vLLM) — uniquement si 2+3
   n'atteignent pas la cible ; risque architectural le plus élevé.

Chaque tentative (y compris les échecs) est loggée avec : levier testé,
config exacte, cold start mesuré (plusieurs runs, pas un seul point),
delta sur le corpus gold si applicable, décision (gardé/rejeté) et
pourquoi. Ce log vit dans un fichier dédié (pas `choix_techniques.md`,
qui reste bref et ne garde que la décision finale retenue).

## Key Assumptions to Validate

- [ ] Le GPU memory snapshot Modal (beta) est compatible avec vLLM tel
      que configuré ici — à tester directement, pas garanti par la doc.
- [ ] L'accès à la feature beta ne nécessite pas d'activation compte
      bloquante côté Modal.
- [ ] Des poids NuExtract3 quantifiés (officiels ou produits en interne)
      existent sans casser le format de sortie JSON attendu par
      `scripts/nuextract_client.py`.
- [ ] Réduire `--gpu-memory-utilization`/`--kv-cache-dtype` ne régresse
      pas silencieusement sur les documents longs (windowing, voir
      `docs/ideas/nuextract-windowing.md`, calé sur `max-model-len=16384`).
- [ ] Un cold start < 1 min reste stable sur plusieurs runs consécutifs
      (pas juste un run chanceux) — la variabilité déjà observée
      (`nuextract_client.py:31-40`) est le vrai risque à couvrir.

## MVP Scope

**In :**
- Instrumentation timing par étape dans `@modal.enter()`.
- Test du GPU memory snapshot Modal (beta).
- Test quantization NuExtract3 (si poids disponibles) + réglages vLLM
  fins + comparaison GPU L4/A10G/A100 à coût comparable.
- Exécution directe par l'agent sur les exemples du corpus gold pour
  mesurer le cold start et vérifier l'absence de régression —
  autorisation explicite donnée par l'utilisateur pour ce chantier
  précis (au moment de l'invocation `/idea-refine`), distincte de
  l'exception DSPy déjà actée dans `CLAUDE.md` mais de même nature :
  scopée à ce chantier, pas une règle générale sur le corpus gold.
- Log de test dédié : chaque tentative, gain/échec, mesures brutes.
- Itération jusqu'à < 1 min ou leviers épuisés.

**Out (pour l'instant) :**
- Changer de moteur d'inférence (vLLM → autre) — dernier recours si 2+3
  échouent.
- Compter sur `scaledown_window` long comme solution — déjà tenté en
  local (60s → 600s, non commité), rejeté comme réponse au problème réel.
- Tensor parallelism / multi-GPU — hors sujet pour un seul GPU L4-class.
- Changer le modèle lui-même (autre architecture NER) — hors scope,
  question de cold start, pas de qualité d'extraction.

## Not Doing (and Why)

- **Changer de moteur d'inférence en premier** — réécriture probable du
  contrat client/serveur (API OpenAI-compatible, multimodal images),
  disproportionné avant d'avoir épuisé les leviers infra/config.
- **Garder le container chaud plus longtemps comme fix** — répond
  confirmé explicitement : le scale-to-zero doit rester réellement
  rapide, pas masqué.
- **Modifier `choix_techniques.md` avec le détail de chaque tentative**
  — contraire à sa règle (bref, cœur de l'app uniquement) ; le détail va
  dans le log dédié, `choix_techniques.md` ne garde que la décision
  finale.

## Open Questions

- Le GPU memory snapshot Modal (beta) nécessite-t-il une activation
  compte spécifique ou un plan payant particulier ? À vérifier dès le
  premier essai.
- NuExtract3 a-t-il des poids quantifiés officiels (numind), ou faut-il
  les produire soi-même (AutoAWQ/AutoGPTQ) — impact direct sur le risque
  de régression de sortie.
- Format et emplacement exact du log de test (nouveau fichier
  `docs/nuextract-cold-start-tests.md` ou autre) — à trancher en
  `/planning-and-task-breakdown`.
