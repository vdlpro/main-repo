# Modele de donnees V2

## themes.csv

Colonnes:
- `theme_slug`: identifiant stable, ex `immobilier`
- `theme_label`: libelle front, ex `Immobilier`
- `enabled`: `1` ou `0`
- `default_cadence_days`: frequence par defaut
- `priority`: `high|normal|low`

## macro_themes.csv

Colonnes:
- `macro_theme_slug`: identifiant stable, ex `finance-assurance-credit`
- `macro_theme_label`: libelle metier, ex `Finance / Assurance / Crédit`
- `enabled`: `1` ou `0`
- `default_cadence_days`: frequence par defaut
- `priority`: `high|normal|low`

## sites.csv

Colonnes:
- `site_id`: identifiant stable interne
- `site`: URL principale
- `name`: libelle source
- `registered_domain`: domaine racine attendu
- `language`
- `source_record_id`
- `sitemap`: URL sitemap principale connue
- `status`: `active|paused|blacklisted|invalid`
- `priority`: `high|normal|low`
- `cadence_days`: cadence cible
- `theme_raw`: valeur brute source
- `theme_primary`: premier theme brut
- `price`
- `visits`
- `unique_visitors`
- `majestic_trust_flow`
- `majestic_ref_domains`
- `semrush_traffic`
- `moz_domain_authority`
- `notes`: commentaire libre

## site_themes.csv

Table de relation many-to-many.

Colonnes:
- `site_id`
- `theme_slug`
- `theme_label`
- `theme_position`

## site_macro_themes.csv

Table de relation many-to-many entre sites et macro-themes.

Colonnes:
- `site_id`
- `macro_theme_slug`
- `macro_theme_label`
- `macro_theme_position`

## theme_map.csv

Mapping des themes detectes dans la source vers les themes V2 et leur macro-theme.

Colonnes:
- `raw_theme`
- `theme_slug`
- `theme_label`
- `macro_theme_slug`
- `macro_theme_label`
- `enabled`
- `default_cadence_days`
- `priority`

## theme_macro_map.csv

Mapping des themes V2 vers les macro-themes.

Colonnes:
- `theme_slug`
- `theme_label`
- `macro_theme_slug`
- `macro_theme_label`

## Sorties dashboard globales

Sous `public/data/all/`:
- `build_meta.json`
- `sellers_summary.json`
- `buyers_summary.json`
- `links_recent.json`
- `network_edges.json`

## Sorties dashboard par macro-theme

Sous `public/data/macros/<macro_theme_slug>/`:
- `build_meta.json`
- `sellers_summary.json`
- `buyers_summary.json`
- `links_recent.json`
- `network_edges.json`

## Manifest

`public/data/manifest.json`

Contient:
- liste des macro-themes
- compteurs globaux
- mapping des chemins de donnees
- date de generation
