# Pipeline NuExtract (spike de comparaison)

## Problem Statement

Comment comparer objectivement le pipeline actuel (PyMuPDF4LLM + LangExtract)
à un second pipeline basé sur NuExtract (serveur auto-hébergé, extraction
structurée directement depuis les pages du PDF, evidence `verbatim-string`),
sur le dataset gold, sans réécrire l'architecture existante ?

## Recommended Direction

V1 : un script autonome (pas un `NerExtractor` branché sur le `Protocol`
existant — NuExtract prend des images de pages en entrée, pas le texte
markdown produit par PyMuPDF4LLM, donc l'intégration au Protocol actuel
n'apporte rien à ce stade). Le document est traité **en une seule fois, sans
découpage** : rendu PDF→PNG par page (PyMuPDF), toutes les images du document
envoyées dans un seul appel `chat/completions` (endpoint OpenAI-compatible
exposé par vLLM + NuExtract3), schéma JSON avec `verbatim-string` sur les
champs à extraire.

Le résultat est mappé vers `ExtractionResult(source="nuextract", ...)` — même
forme que le pipeline actuel — pour réutiliser tel quel le scoring existant
(`scripts/gold_matching.py`) et produire un CSV comparable aux runs DSPy déjà
présents dans `tasks/`.

Le windowing 4-6 pages + overlap initialement envisagé est repoussé : le
corpus gold (≤12 pages/doc) tient largement sous la limite de 99 images par
requête de NuExtract, donc la complexité de fusion cross-fenêtre (doublons
aux frontières, arbitrage) n'a rien à prouver sur ce corpus pour l'instant.

## Key Assumptions to Validate

- [ ] Le serveur vLLM + NuExtract3 est déployé et accessible depuis l'app —
      à confirmer (URL, auth) avant tout code client.
- [ ] Les documents gold tiennent dans la limite 99 images / 131k tokens de
      contexte du serveur — a priori oui vu leur taille, à vérifier sur le
      premier run réel (fait par l'humain, pas par Claude).
- [ ] Le endpoint `/v1/chat/completions` accepte le schéma NuExtract via
      `extra_body.chat_template_kwargs` — à valider avec un appel minimal
      (1-2 champs, 2-3 documents) avant de brancher tous les champs du gold.
- [ ] `verbatim-string` garantit la fidélité du texte extrait mais ne donne
      pas nativement de position (page/bbox) — à confirmer en observant une
      vraie réponse serveur.

## MVP Scope

**In :**
- Script autonome (`scripts/nuextract_pipeline.py` ou équivalent) : PDF →
  images par page → un appel `chat/completions` par document → parsing JSON
  → `list[ExtractionResult]`.
- Réutilisation du scoring existant (`gold_matching.classify_field`,
  `precision_recall_f1`) pour produire des métriques comparables au pipeline
  actuel.
- Sortie CSV (pattern déjà utilisé pour les runs DSPy).

**Out (voir Not Doing) :** windowing/overlap, arbitrage cross-fenêtre,
grounding précis, intégration au `Protocol` `NerExtractor`, UI, sélection de
pipeline en prod.

## Not Doing (and Why)

- **Windowing 4-6 pages + overlap** — reporté : le corpus gold tient dans une
  fenêtre unique, la complexité de fusion cross-fenêtre n'apporte rien tant
  que ce n'est pas exercé par un doc réel trop long.
- **Grounding `page_number`/`text_position` précis** — `verbatim-string`
  garantit le texte, pas une position ; le reconstruire demanderait un texte
  de référence par page (nouveau code PDF) pour un gain secondaire — la
  comparaison porte d'abord sur la valeur extraite.
- **Intégration comme `NerExtractor` via le `Protocol` existant** — NuExtract
  prend des images de pages, pas le texte markdown de PyMuPDF4LLM ; forcer
  l'intégration ajouterait de la friction sans bénéfice pour un spike.
- **Run automatique sur le corpus gold par Claude** — seul l'humain lance la
  comparaison réelle (règle CLAUDE.md ; ce chantier n'est pas du DSPy, donc
  pas d'exception ici).

## Open Questions

- Où le serveur vLLM/NuExtract est-il hébergé, et comment l'app y accède-t-elle
  (URL, auth) ?
- Faut-il malgré tout un grounding approximatif (page) pour rendre les
  résultats interprétables lors d'une revue manuelle, même sans précision au
  caractère près ?
