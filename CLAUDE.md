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

Traitement PDF + NER (remplace les mocks `MockPdfTextExtractor`/`MockNerExtractor` par une implémentation réelle) :
* traite les PDF avec PyMuPDF4LLM
* implémente `LangExtractNerExtractor` derrière le `Protocol` `NerExtractor` déjà en place (`app/tools/`), pour rester swappable sur une autre solution NER sans toucher routes/UI/modèles
* chaque `ExtractionResult` est enrichi d'un grounding textuel : numéro de page + position/citation dans le texte extrait (pas de bounding box à cette étape)
* les runs d'extraction restent persistés avec leurs métadonnées (nom du fichier source), comme aujourd'hui
* modèle Gemini gratuit, configuré via `GOOGLE_GENERATIVE_AI_API_KEY` et `LLM_MODEL` dans `.env`
* dataset de test minimal : un test pytest opt-in (skip si pas de clé API dans l'env) qui appelle le vrai modèle Gemini sur 1-2 PDF factices avec des valeurs attendues connues
* une fois ce NER réel en place, valider manuellement l'ingestion d'un PDF réel et inspecter ce qui a été extrait
* pipeline le plus simple possible tout en restant très propre pour un AI engineer


* Étape 2 : Création d'un workflow agentique de génération de données d'entraînement

* Étape 3 : Entraînement d'un modèle léger basé sur les données virtuelles.

* 