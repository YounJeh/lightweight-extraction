DoD : 
* Création d'un dataset gold plus important
    * versioning des datasets gold avec MLFlow si gratuit ou autre solution robuste et state of the art et gratuite
    * Définition de métrics pour l'évaluation des datasets


Amélioration d'UI : 
* P4 : Dans la page des champs définits, ajouter une option d'importation d'un fichier de fields. les entrées acceptées sont .csv, .tsv, .xlsx. Tu dois dans un premier temps faire une validation pydantic pour vérifier que toutes les colonnes des champs sont définis. On accepete les données avec plus de colonnes mais on doit avoir toutes les colonnes requises. Sinon afficher un message d'erreur avec les colonnes manquantes.
* P5 : 

DB : 
* P3 : Script pour réinitialise la DB à 0
* Script pour importer directement le Data set gold

Amélioration pipeline NER


Data set gold :
* permettre d'ajouter des exemples qui seront integrées par langextract
* utiliser le type définit pour chaque exemple (Pydantic si pas directement intégré dans LangExtract). le type définit la sortie valeur mais il faut également une sortie de texte qui donne le contexte de la valeur extraite.
* Rechercher des contrats PV existants sur internet


