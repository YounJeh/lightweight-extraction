# Bouton "Tout sélectionner / désélectionner" global (page extraction)

## Problem Statement
Comment permettre à l'utilisateur de sélectionner ou désélectionner tous les champs de toutes les sections en une seule action, sans dupliquer la complexité du pattern déjà existant au niveau section ?

## Recommended Direction
La page d'extraction expose déjà un "Tout sélectionner"/"Tout désélectionner" par section (`_field_section_group` dans [components.py](app/ui/components.py#L180-L204)), avec un script JS (`_field_group_selection_script`) qui gère le comptage par groupe. Il manque l'équivalent au niveau du formulaire entier.

On ajoute un bouton bascule unique, placé juste sous le label "Champs à extraire" et au-dessus de la liste des sections. Son libellé reflète l'état courant :
- si tous les champs sont cochés → "Tout désélectionner"
- sinon (aucun ou certains cochés) → "Tout sélectionner"

Au clic, il coche ou décoche l'ensemble des cases dans `.field-groups`, met à jour les compteurs par section (réutilise `updateCount`), et recalcule son propre libellé. Un `change` sur n'importe quelle case du formulaire recalcule aussi ce libellé, pour rester synchronisé avec les toggles par section existants.

Ce choix reste cohérent avec le pattern déjà en place (un seul bouton bascule plutôt que deux, comme demandé) et ne casse rien : c'est une extension du script existant, pas une réécriture.

## Key Assumptions to Validate
- [ ] Un bouton bascule est plus lisible qu'une paire de boutons — à confirmer visuellement une fois posé dans l'UI (vérifier que le changement de libellé ne "saute" pas de façon déroutante).
- [ ] "Tout désélectionner" doit vider même les champs pré-sélectionnés par défaut (`_DEFAULT_CHECKED_FIELD_COUNT`) — comportement confirmé par l'utilisateur, à vérifier qu'aucun champ n'est requis côté serveur pour lancer une extraction avec zéro champ coché (le POST retourne déjà une erreur si `selected_fields` est vide, donc pas de risque).

## MVP Scope
**Dans le scope :**
- Un bouton bascule global au-dessus des groupes de sections.
- Logique JS : coche/décoche tout, recalcule les compteurs par section existants, met à jour son propre libellé au clic et sur tout `change` de case.
- Libellé initial calculé côté serveur (Python) à partir de `default_checked_ids` vs nombre total de champs, pour éviter un flash visuel au chargement.

**Hors scope (implémenté dans ce lot) :** rien d'autre — la fonctionnalité est autonome et se branche sur le script existant sans le réécrire.

## Not Doing (and Why)
- **Compteur global "X/N sélectionnés"** — pas demandé, et le compteur par section suffit déjà à donner une vue d'ensemble ; ajouter un total dupliquerait l'info pour un gain marginal.
- **Bouton dupliqué en pied de formulaire** — l'utilisateur a choisi le placement unique en haut ; le formulaire n'est pas assez long aujourd'hui pour justifier un rappel en bas.
- **État "reset à la présélection par défaut"** — l'utilisateur a choisi la sémantique littérale ("tout désélectionner" = zéro champ), pas un état de réinitialisation intermédiaire.

## Open Questions
Aucune — le scope est suffisamment restreint (extension d'un script déjà en place) pour passer directement à l'implémentation.
