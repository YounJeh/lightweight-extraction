# Windowing NuExtract pour les PDF longs

## Problem Statement

Comment traiter, dans `nuextract_client.extract`, les documents dont le
nombre de pages dépasse la fenêtre de contexte du serveur NuExtract
(observé en réel : 3/14 documents gold en `400 context length exceeded`,
1/14 en `400 at most 15 images`), sans réécrire l'API publique de
`extract()` ni ajouter d'arbitrage LLM pour cette version ?

## Recommended Direction

`extract()` garde exactement la même signature et le même contrat
(`pdf_bytes`, `fields` → `list[ExtractionResult]`) — le découpage devient
un détail interne, transparent pour tous les appelants existants
(`nuextract_gold_langfuse_eval.build_task`, le smoke test, les tests) :

- Si `page_count(pdf_bytes) <= 5` (le cas d'aujourd'hui pour la majorité
  du corpus gold, voir données réelles ci-dessous) : comportement inchangé,
  un seul appel `chat/completions`.
- Sinon : découpage en fenêtres de **5 pages avec overlap de 1 page** (pas
  4 fenêtre = 4 pages utiles progressées par appel), un appel
  `chat/completions` par fenêtre (réutilise tel quel `render_pdf_pages`
  restreint au sous-ensemble de pages, `build_template`, `parse_response`,
  `_create_completion_with_retries` — aucun de ces éléments ne change).
- Fusion par champ : **la première fenêtre (dans l'ordre du document) qui
  renvoie une valeur non vide gagne** — pas d'appel LLM d'arbitrage pour
  cette version (décidé explicitement).

**Pourquoi 5 pages/1 page d'overlap :** les 3 échecs `400` réels donnent
~2000-2200 tokens/page (12-14 pages → 25879-30175 tokens, limite serveur
16384). 5 pages ≈ 11000 tokens, marge confortable sous la limite y compris
avec le prompt/template. Reste sous la limite de 15 images/prompt
(`--limit-mm-per-prompt`) avec large marge. Le corpus réel (`data_test/`)
va jusqu'à 25 pages — le découpage doit boucler sur plus de deux fenêtres,
pas juste un split en deux.

## Key Assumptions to Validate

- [ ] 5 pages tient effectivement sous 16384 tokens sur tous les documents
      du corpus, pas seulement les 3 qui ont échoué — l'estimation
      ~2000-2200 tokens/page vient de 3 points de données seulement,
      aucun comptage de tokens réel effectué. À valider sur le prochain
      run réel (fait par l'humain).
- [ ] "1ère fenêtre non vide gagne" reste une simplification acceptable —
      un candidat plus tardif mais plus correct (ex. un montant corrigé en
      annexe) serait ignoré. Accepté pour cette version (décision déjà
      actée dans le cadrage initial du spike, reconfirmée ici).
- [ ] La latence par document augmente proportionnellement au nombre de
      fenêtres (appels séquentiels, pas parallélisés) — acceptable pour un
      outil de comparaison, pas une contrainte de SLA production.

## MVP Scope

**In :**
- Détection du nombre de pages et décision windowing/pas-windowing dans
  `extract()`.
- Découpage 5 pages / overlap 1 page, boucle gérant un nombre arbitraire
  de fenêtres (pas juste 2).
- Fusion par champ : première valeur non vide, dans l'ordre des fenêtres.
- Réutilisation intégrale de `render_pdf_pages`/`build_template`/
  `parse_response`/`_create_completion_with_retries` — aucune de ces
  fonctions n'est réécrite, seulement appelée différemment.

**Out :** arbitrage LLM cross-fenêtre ; taille de fenêtre dynamique basée
sur un vrai comptage de tokens (heuristique par nombre de pages seulement) ;
parallélisation des appels de fenêtres d'un même document ; changement de
signature ou de contrat public de `extract()`.

## Not Doing (and Why)

- **Arbitrage LLM entre fenêtres** — décidé explicitement par l'utilisateur
  pour cette version : la première valeur non vide gagne, un second appel
  LLM par conflit ajouterait de la complexité et du coût pour un gain
  incertain à ce stade.
- **Taille de fenêtre adaptative (comptage de tokens réel)** — une
  heuristique fixe par nombre de pages (5) est plus simple, cohérente avec
  la demande d'origine ("4-6 pages"), et suffisante tant qu'elle n'est pas
  invalidée par un run réel.
- **Parallélisation des fenêtres au sein d'un document** — séquentiel plus
  simple à raisonner et à fusionner ; un document long prendra
  proportionnellement plus de temps, acceptable pour ce spike.

## Open Questions

- Le seuil de déclenchement (`page_count > 5`) doit-il avoir une marge en
  dessous de la taille de fenêtre, ou rester exactement égal à elle ? Pas
  bloquant, à ajuster si le premier run réel montre un cas limite.
