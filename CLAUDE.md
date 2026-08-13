# lightweight-extraction

L'objectif est de créer une interface simple permettant à partir d'un faible jeu de données annoter de construire un pipeline d'extraction NER précis.

Ce pipeline inclus 
* le traitement de données au format PDF.
* un système agentique de génération de données
* l'entrainement (finetuning) d'un modèle local léger entrainer sur son modèle professeur
* Un système d'évaluation agentique et NER permettant de comparer différents pipeline et LLM providers
* une UI légère et moderne permettant à l'utilisateur d'importer ses données et de lancer des recherhce dans de nouveau documents
* un DB SQLLite pour la persistance de la données

ROADMAP : 

* Étape 1 : création d'un pipeline 

l'utilisateur doit pouvoir ajouter/mettre à jour/supprimer des champs (titre, définition, exemples) depuis l'UI et persistance sur SQLLite.

```console
Python 3.12
│
├── FastHTML
│      UI + serveur
│
├── PyMuPDF4LLM
│      PDF → texte
│
├── LangExtract
│      extraction + grounding
│
├── SQLLite
│      persistance des champs
│
├── Pydantic
│      domain models
│
├── pytest
│
├── uv
```

UI : Barre latérale avec :
* une page qui donne un liste déroulante de tous les champs et leurs attributs et qui permet de mettre à jour/créer/suppirimer les champs
* une page permettant d'uploader un pdf et de faire une NER en ayant préalablement cocher dans une liste les champs à extraire à partir de ceux disponibles



* Étape 2 : Création d'un workflow agentique de génération de données d'entraînement

* Étape 3 : Entraînement d'un modèle léger basé sur les données virtuelles.

* 