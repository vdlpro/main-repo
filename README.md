# Analyse Full Ereferer

V2 multi-thematique du pipeline de monitoring sitemap / liens.

Objectifs:
- scaler au-dela du projet VDL actuel
- conserver un dashboard unique avec les memes vues
- ajouter un filtre `macro-theme` et une vue `toutes thematiques`
- preparer une execution par vagues, sans casser l'existant

Etat actuel du repo:
- architecture cible posee
- schema de catalogue multi-thematique defini
- workflow incremental GitHub en place
- import multi-theme depuis la base Ereferer en place
- relations site -> macro-theme en place
- generation de sorties dashboard structurees en `all` + `macros`
- dashboard statique publie dans `public/index.html`
- catalogue nettoye aux seuls sites sitemap-valides
- etat runtime reset pour repartir sur une baseline propre

## Structure

- `catalog/`: fichiers source de themes et de sites
- `catalog/`: themes, macro-themes, sites et relations
- `config/`: configuration pipeline et schedulers
- `data/`: etat local, evenements, agregats
- `docs/`: documentation architecture et modele de donnees
- `public/data/`: sorties dashboard publiees
- `scripts/`: scripts Python du pipeline

## Demarrage

```powershell
cd "C:\Users\aweec\Documents\Analyse Full Ereferer"
python scripts\finalize_catalog.py
python scripts\crawl_v2.py
python scripts\run_pipeline.py
```

## Scripts utiles

- `scripts/import_ereferer_catalog.py`
  importe le catalogue source et preserve les champs locaux (`sitemap`, `status`, `notes`, etc.)
- `scripts/finalize_catalog.py`
  garde uniquement les sites actifs avec sitemap valide, regenere les relations et remet a zero l'etat runtime
- `scripts/crawl_v2.py`
  workflow incremental:
  - baseline `snapshot + ever_seen` au premier passage
  - crawl des pages uniquement pour les nouvelles URLs detectees ensuite
- `scripts/exclude_inoperable_sites.py`
  marque en `invalid` les sites rejetes de maniere evidente (`403`, `404`, `no_sitemap_found`)
- `scripts/audit_sitemaps.py`
  audite les sitemaps en mode massif `sitemap-only`, par lots, sans toucher aux events
- `scripts/run_pipeline.py`
  reconstruit les datasets `all` et `macros`

## Test GitHub Actions

Le workflow principal est `.github/workflows/v2-pipeline.yml`.

Pour un premier test manuel sur petit lot:
- `max_sites_override`: `50` ou `100`
- `sitemap_workers`: `8` ou `12`
- `page_workers`: `8` ou `12`
- `seed_initial_urls`: `0`

Important:
- `seed_initial_urls=0` signifie:
  - premier passage: pose uniquement la baseline sitemap
  - aucun crawl historique des pages existantes
  - seuls les futurs deltas sitemap produiront des `page_events` et `link_events`

## Audit sitemap par lot

```powershell
cd "C:\Users\aweec\Documents\Analyse Full Ereferer"
$env:AUDIT_BATCH_INDEX='1'
$env:AUDIT_BATCH_SIZE='2000'
$env:AUDIT_WORKERS='24'
$env:AUDIT_SECOND_PASS_WORKERS='8'
python scripts\audit_sitemaps.py
```

Le script checkpoint automatiquement pendant l'audit:
- `data/state/sitemap_audit/checkpoints/`
- `data/state/sitemap_audit/batches/`
- `data/state/sitemap_audit/summaries/`

Si un batch est interrompu, relancer la meme commande reprend le batch au lieu de repartir de zero.

## Suite logique

1. tester le workflow GitHub sur petit lot
2. verifier que le premier run ne cree que la baseline
3. laisser un second run confirmer la detection des vraies nouvelles URLs
4. ensuite seulement ajuster cadence, volumetrie et decoupage par repo/theme
