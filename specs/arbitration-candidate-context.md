# Spec : Contexte textuel des candidats dans l'arbitrage de conflit

## Objectif

Bug rapporté : lors d'un arbitrage entre candidats distincts pour un même
champ (`_arbitrate`, `app/tools/ner_langextract.py`), le LLM arbitre ne voit
que les valeurs brutes (`Candidat 1 : 30`, `Candidat 2 : 15`...), sans savoir
de quelle clause du document elles proviennent. Résultat observé : un
candidat provenant d'une clause non pertinente (ex. préavis de résiliation)
est choisi à la place du candidat réellement conforme à la définition du
champ (ex. durée de validité du contrat), faute de contexte pour les
distinguer.

**Succès =** chaque candidat envoyé à l'arbitrage est accompagné du texte qui
l'entoure dans le document source et de sa page, pour que le LLM arbitre
puisse identifier la clause dont chaque valeur est issue avant de choisir.

Décision issue d'une session `idea-refine` (voir historique de conversation) :
Direction A retenue — injection de contexte minimale, en réutilisant le
mécanisme de grounding déjà existant (`_locate`), sans score de proximité au
mot-clé ni escalade UI (pistes notées en Open Questions, hors scope ici).

## Contexte technique (root cause)

`_arbitrate` (L204) construit aujourd'hui son prompt via `_arbitration_text`
(L251) à partir des seules `extraction_text` des candidats. Le texte source
complet (`text`) est disponible dans `_extract` (L95) et sert déjà à
localiser le candidat **gagnant** après coup via `_locate` (L349,
`page_number` + snippet de `_CONTEXT_CHARS=40` caractères) — mais ce calcul
n'est fait qu'une fois l'arbitrage terminé, jamais pour aider l'arbitrage
lui-même. `text` n'est pas propagé jusqu'à `_arbitrate`/`_select_candidate`.

## Décision de correction

1. Propager `text` dans la chaîne d'appel jusqu'à `_arbitrate` :
   `_extract` → `_select_candidate` → `_arbitrate` (actuellement ces deux
   fonctions ne reçoivent pas `text`).
2. Dans `_arbitrate`, calculer `_locate(text, candidate.char_interval.start_pos,
   candidate.char_interval.end_pos)` pour **chaque** candidat (pas seulement
   le gagnant), avant de construire le prompt.
3. `_arbitration_text` inclut, par candidat, la valeur, la page et le
   snippet :
   ```
   Champ : Durée de validité du contrat en jour
   Définition : Durée de validité du contrat en jour et converti en jour si en mois

   Candidat 1 : 30 (page 2, contexte : "...préavis de résiliation fixé à 30 jours avant l'échéance...")
   Candidat 2 : 15 (page 1, contexte : "...durée de validité du présent contrat est fixée à 15 jours...")
   ```
4. `_arbitration_example` (L270) est mis à jour pour montrer ce même format
   dans le few-shot, afin que le LLM interprète correctement la structure
   `(page X, contexte : "...")` plutôt que de la recopier dans sa réponse.
5. La logique de correspondance en sortie (`_arbitrate`, L238-248 : normaliser
   la réponse du LLM et la comparer à `extraction_text` des candidats) reste
   inchangée — elle ne dépend pas du format d'entrée, seul le prompt change.
6. `_CONTEXT_CHARS` reste à 40 pour ce MVP (pas d'élargissement spécifique à
   l'arbitrage) — voir Open Questions si ça s'avère insuffisant en pratique.

Le fix reste **entièrement interne à `app/tools/ner_langextract.py`** :
aucun changement de `Protocol`, de route, d'UI ou de schéma DB — cohérent
avec les Boundaries de `specs/pdf-ner-real.md` et `specs/dedupe-extraction-results.md`.

## Testing Strategy

- Tests **offline** (pas d'appel réseau), ajoutés à
  `tests/test_ner_langextract_dedupe.py` (même fichier que le test de
  conflit existant `test_extract_arbitrates_genuine_conflict_via_second_llm_call`,
  même style : monkeypatch `ner_langextract.langextract.extract`, deux
  candidats groundés à des positions différentes dans un texte de test) :
  - Le prompt envoyé au **second** appel `langextract.extract`
    (`calls[1]["prompt_description"]`) contient le snippet de texte entourant
    **chacun** des candidats (pas seulement leurs valeurs brutes).
  - Le numéro de page de chaque candidat apparaît dans ce même prompt.
  - Le comportement existant (sélection du candidat dont le texte
    correspond à la réponse normalisée du LLM, repli sur la première
    occurrence si l'arbitrage est imparsable) n'est pas affecté — les tests
    existants (`test_extract_arbitrates_genuine_conflict_via_second_llm_call`,
    `test_extract_falls_back_to_first_occurrence_when_arbitration_is_unparseable`)
    doivent continuer à passer sans modification de leurs assertions.
- Le test live existant (`tests/test_ner_langextract_live.py`,
  `@pytest.mark.live`) reste inchangé et sert de garde-fou end-to-end avec
  le vrai modèle — à revérifier après ce changement.
- Pas de nouveau test live dédié : le contexte de snippet n'a pas besoin
  d'un appel réseau réel pour être vérifié (c'est une transformation de
  prompt, testable offline).

## Boundaries

- **Toujours faire :** garder la signature de `NerExtractor.extract()`
  inchangée ; ne pas toucher `app/routes/`, `app/ui/`, `app/db.py`,
  `app/models.py` ; garder `_arbitrate`/`_select_candidate` internes au
  module (pas d'export public nouveau).
- **Demander avant de faire :** élargir `_CONTEXT_CHARS` (impact potentiel
  sur les snippets déjà affichés à l'utilisateur pour les résultats finaux,
  si la constante est partagée) — voir Open Questions.
- **Ne jamais faire :** changer le format de sortie attendu de l'arbitrage
  (`extraction_class = 'selection'`, recopie mot pour mot de la valeur) —
  seul le prompt d'entrée change, pas le contrat de sortie.

## Success Criteria

- [x] `_arbitrate` reçoit le texte source et calcule un snippet + page pour
      chaque candidat avant de construire le prompt d'arbitrage.
- [x] `_arbitration_text` affiche ce contexte pour chaque candidat, dans un
      format cohérent avec l'exemple few-shot mis à jour.
- [x] Test offline dédié : le prompt du second appel LLM contient bien le
      snippet et la page de chaque candidat en conflit.
- [x] Aucune régression sur la suite existante (`uv run pytest -m "not live"`
      — 148 passed, 1 deselected ; l'échec de `test_fields_routes.py` est
      préexistant et sans rapport, causé par `DATASET GOLD.csv` déjà modifié
      dans l'arbre de travail avant ce changement).
- [ ] Test live revérifié manuellement (`uv run pytest -m live`) si une clé
      API est disponible.

## Open Questions

- `_CONTEXT_CHARS = 40` suffira-t-il à inclure l'indice disqualifiant (ex.
  le mot "préavis") dans le snippet ? À observer sur des cas réels après
  déploiement ; si insuffisant, élargir la fenêtre spécifiquement pour
  l'arbitrage (sans toucher au grounding du résultat final) plutôt que
  d'augmenter `_CONTEXT_CHARS` globalement.
- Si le nombre de candidats en conflit est élevé (comme le cas à 8 candidats
  qui a motivé ce fix), le prompt d'arbitrage grossit proportionnellement
  (snippet × N candidats) — pas de limite mise en place pour l'instant ;
  à surveiller via Langfuse si ça devient un problème de coût/latence.
- Pistes délibérément hors scope ici (notées lors de l'idea-refine) : score
  de proximité au mot-clé du champ, `reasoning` tracé sur la sélection,
  escalade UI en cas de conflit fort.
