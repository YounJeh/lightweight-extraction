# Validation des optimisations OCR (dpi réduit + seuil de saut)

## Problem Statement
Comment savoir, avant de toucher au code de l'app, si baisser `ocr_dpi`
et/ou court-circuiter l'OCR sur les petites images réduit vraiment le coût
de l'extraction PDF sans faire disparaître des valeurs que le pipeline doit
pouvoir extraire ?

## Recommended Direction
Un script de validation autonome (aucun changement à `app/`) qui mesure,
sur les 14 documents de `data_test/` ayant des annotations dans
`tests/data/dataset_gold_devis.yaml`, l'effet de plusieurs configurations
sur deux axes : le temps total d'extraction PDF→texte, et la présence des
valeurs gold non-nulles dans le texte markdown brut produit.

Le proxy retenu — "la valeur gold apparaît-elle encore comme sous-chaîne du
texte OCR brut" — isole volontairement l'effet de l'extraction PDF du bruit
du pipeline NER (pas d'appel LLM, déterministe, gratuit). Ce n'est pas une
garantie que le NER en aval retrouvera la valeur, juste un signal précoce
et peu coûteux de régression.

**Découverte en amont (à traiter comme un résultat de la validation, pas
une prémisse) :** la distribution réelle de `img_area`/`text_len` sur les
85 pages qui déclenchent `needs_ocr` dans ce corpus ne montre **aucune
séparation nette** entre pages "juste un logo" et pages "vraiment
scannées" — la page 12 de `104__DEVIS_25110230_VERSION_A03.pdf` (photocopie
de CGV, notre cas de référence) a un `img_area=0.0164`, plus bas que la
plupart des logos. Un seuil simple sur `img_area` seul risque donc de
couper exactement le cas qu'on veut préserver. La validation doit
déterminer s'il existe malgré tout un seuil (ou une combinaison de
signaux) praticable — pas partir du principe que oui.

## Key Assumptions to Validate
- [ ] La présence de la valeur gold en sous-chaîne du texte OCR brut est un
      proxy suffisant pour "pas de régression" — vérifiable en relançant,
      une fois une config candidate choisie, le pipeline NER complet dessus
      (hors scope de cette validation, mais condition avant tout
      déploiement réel).
- [ ] Il existe au moins une configuration (palier de `ocr_dpi`, et/ou
      seuil B, et/ou combinaison des deux) qui réduit significativement le
      temps total sans perdre aucune valeur gold sur les 14 documents — à
      tester explicitement, pas supposé.
- [ ] Si un seuil B existe, il généralise au-delà de ce corpus de 14
      documents (échantillon petit, biaisé vers des PDF ENTECH/ADIWATT) —
      non vérifiable dans cette validation, juste un risque à noter dans le
      rapport final.

## MVP Scope
**Dans le périmètre :**
- Script Python ad hoc (hors `app/`, ex. `scripts/validate_ocr_tuning.py`
  ou notebook jetable) qui, pour chaque document gold-annoté :
  1. Extrait le texte à `ocr_dpi` = 150 (référence actuelle), 120, 100, 90,
     72 — seuil B désactivé, pour isoler l'effet de A seul.
  2. Applique plusieurs seuils B candidats (dérivés de la distribution
     mesurée ci-dessus, plusieurs valeurs testées, pas une seule présumée
     bonne) à `ocr_dpi=150`, pour isoler l'effet de B seul.
  3. Teste la meilleure combinaison A+B trouvée aux étapes précédentes, sur
     le cas le plus coûteux (`26-0743 Tournan V1 2026-03-20.pdf`), pour
     voir l'effet cumulé.
- Pour chaque config : temps total d'extraction, et pour chaque valeur gold
  non-nulle du document, présent/absent dans le texte extrait (avec une
  comparaison normalisée — casse/accents — pour éviter les faux négatifs
  triviaux).
- Un rapport lisible (tableau config × [temps, % valeurs gold présentes,
  liste des valeurs perdues le cas échéant]) — pas de décision automatique,
  matière à trancher ensuite.

**Hors périmètre (voir Not Doing).**

## Not Doing (and Why)
- **Relancer le pipeline NER (Gemini) complet dans cette validation** —
  coût réel en appels LLM, plus lent, et la variance du LLM deviendrait un
  facteur confondant qui empêcherait d'attribuer un écart à l'OCR ou au
  LLM. Réservé à une vérification finale, une fois une config candidate
  choisie sur la base du proxy texte brut.
- **Tester sur les 16 fichiers de `data_test/`** — 2 fichiers n'ont pas
  d'annotations gold, donc pas de mesure objective de régression possible
  dessus pour l'instant. On peut les regarder informellement mais ils ne
  comptent pas dans le rapport chiffré.
- **Implémenter le changement dans `app/tools/pdf_pymupdf4llm.py`** —
  explicitement demandé : validation seule à ce stade.
- **Construire un classifieur ou un seuil adaptatif sophistiqué pour B** —
  si la distribution ne permet pas un seuil simple praticable, on le
  documente et on s'arrête là pour cette itération plutôt que de
  sur-ingénierer une solution pour un problème qui n'a peut-être pas de
  solution "seuil unique".

## Open Questions
- Si aucune configuration testée ne s'avère satisfaisante (perte de
  valeurs gold), abandonne-t-on A/B pour de bon, ou explore-t-on quand même
  les pistes plus lourdes évoquées précédemment (parallélisation,
  recadrage direct sur la zone image via `page.get_image_rects()`) ?
- Faut-il distinguer, dans le rapport, une valeur "perdue à cause de notre
  changement" d'une valeur "déjà absente avant tout changement" (ex. si le
  pipeline actuel échouait déjà à extraire certaines valeurs du gold
  yaml) ? Sans cette distinction, le rapport risque de sur-attribuer des
  échecs préexistants à l'optimisation testée.
