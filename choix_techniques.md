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
endroits du document (extractions groundées mais divergentes).

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
