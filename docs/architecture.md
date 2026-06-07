# Architecture cible V2

## Principes

- ne pas toucher au projet VDL historique
- separer clairement code, catalogue, etat, evenements et publication
- garder le repo leger: code + config + sorties dashboard compactes
- preparer un futur decoupage par macro-theme, repo ou compte GitHub si necessaire

## Couches

### 1. Catalogue

Source de verite des sites suivis.

Fichiers:
- `catalog/themes.csv`
- `catalog/macro_themes.csv`
- `catalog/sites.csv`
- `catalog/site_themes.csv`
- `catalog/site_macro_themes.csv`

### 2. Etat local

Etat technique du suivi, potentiellement volumineux.

Exemples:
- dernier sitemap tente
- dernier succes
- health score
- exclusions techniques
- stats de cadence

Emplacement:
- `data/state/`

Regle:
- cet etat ne doit pas etre central dans Git a grande echelle

### 3. Evenements

Sorties brutes exploitables du pipeline.

- `data/events/pages/*.jsonl.gz`
- `data/events/links/*.jsonl.gz`

### 4. Agregats

Sorties intermediaires reconstruites depuis les evenements.

- `data/aggregates/latest/`

### 5. Publication dashboard

JSON compacts pour le front:
- global
- par macro-theme

Emplacement:
- `public/data/`

## Modele de scale recommande

### Court terme

- un repo principal multi-theme
- un seul dashboard
- pipeline par vagues
- filtre front par macro-theme + vue toutes thematiques

### Moyen terme

- un repo par macro-theme ou groupe de macro-themes
- un repo central de publication dashboard

### Long terme

- runner self-hosted
- etat local hors Git
- publication des seuls agregats finaux
- test local des sitemaps rejetes avant exclusion du catalogue
