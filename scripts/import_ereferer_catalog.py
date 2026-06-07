from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

try:
    import tldextract
except ImportError:  # pragma: no cover
    tldextract = None


RAW_CATALOG_HEADERS = [
    "id",
    "url",
    "name",
    "language",
    "categories_text",
    "tags",
    "partnership",
    "price",
    "visits",
    "unique_visitors",
    "hide_url",
    "favorite_flag",
    "google_news_label",
    "limited_time_value",
    "delay_value",
    "number_places",
    "created_at",
    "majestic_trust_flow",
    "majestic_citation_flow",
    "majestic_backlinks",
    "majestic_edu_backlinks",
    "majestic_gov_backlinks",
    "majestic_ref_domains",
    "majestic_categories",
    "semrush_traffic",
    "semrush_keyword",
    "semrush_traffic_cost",
    "moz_domain_authority",
    "moz_page_authority",
    "google_news",
    "google_analytics",
    "alexa_rank",
    "archive_age_date",
    "archive_age_y",
    "archive_age_m",
    "archive_age_d",
    "whois_age_date",
    "whois_age_y",
    "whois_age_m",
    "whois_age_d",
    "pub_words",
    "pub_links",
    "pub_images_min",
    "pub_images_max",
    "pub_h1",
    "pub_h2_min",
    "pub_h2_max",
    "pub_h3_min",
    "pub_h3_max",
    "pub_meta_title",
    "pub_meta_description",
    "pub_bold_text",
    "pub_italic_text",
    "pub_ul_tag",
    "pub_webmaster_anchor",
    "pub_authorized_anchor",
    "ttf1_category",
    "ttf1_score",
    "ttf1_ratio",
    "ttf2_category",
    "ttf2_score",
    "ttf2_ratio",
    "ttf3_category",
    "ttf3_score",
    "ttf3_ratio",
]

THEME_HEADERS = [
    "theme_slug",
    "theme_label",
    "enabled",
    "default_cadence_days",
    "priority",
]

MACRO_THEME_HEADERS = [
    "macro_theme_slug",
    "macro_theme_label",
    "enabled",
    "default_cadence_days",
    "priority",
]

THEME_MACRO_MAP_HEADERS = [
    "theme_slug",
    "theme_label",
    "macro_theme_slug",
    "macro_theme_label",
]

THEME_MAP_HEADERS = [
    "raw_theme",
    "theme_slug",
    "theme_label",
    "macro_theme_slug",
    "macro_theme_label",
    "enabled",
    "default_cadence_days",
    "priority",
]

SITE_HEADERS = [
    "site_id",
    "site",
    "name",
    "registered_domain",
    "language",
    "source_record_id",
    "sitemap",
    "status",
    "priority",
    "cadence_days",
    "theme_raw",
    "theme_primary",
    "price",
    "visits",
    "unique_visitors",
    "majestic_trust_flow",
    "majestic_ref_domains",
    "semrush_traffic",
    "moz_domain_authority",
    "notes",
]

SITE_THEME_HEADERS = [
    "site_id",
    "theme_slug",
    "theme_label",
    "theme_position",
]

SITE_MACRO_THEME_HEADERS = [
    "site_id",
    "macro_theme_slug",
    "macro_theme_label",
    "macro_theme_position",
]

MACRO_THEME_DEFINITIONS = [
    {
        "macro_theme_label": "Actualités & Médias",
        "theme_labels": [
            "Actualités (généraliste)",
            "Société",
            "Cinéma",
            "Musique",
            "Littérature",
            "Photographie",
            "Événement",
        ],
    },
    {
        "macro_theme_label": "Entreprise & Formation",
        "theme_labels": ["Entreprise", "Enseignement & Formation"],
    },
    {
        "macro_theme_label": "Santé / Bien-être / Beauté",
        "theme_labels": ["Santé", "Bien-Être", "Beauté", "Sénior"],
    },
    {
        "macro_theme_label": "Maison / Déco / Jardin",
        "theme_labels": ["Maison", "Décoration", "Jardin"],
    },
    {
        "macro_theme_label": "High-Tech / Informatique / Web",
        "theme_labels": ["High-Tech", "Informatique", "Webmasters", "Téléphone & Smartphone"],
    },
    {
        "macro_theme_label": "Voyage / Local",
        "theme_labels": ["Voyage & Tourisme", "Villes & Villages"],
    },
    {
        "macro_theme_label": "Mode / Shopping / E-commerce",
        "theme_labels": ["Mode", "E-commerce", "Cadeaux"],
    },
    {
        "macro_theme_label": "Sport / Loisirs / Jeux",
        "theme_labels": ["Sport & Loisirs", "Sport", "Jeux", "Jeux d'argent"],
    },
    {
        "macro_theme_label": "Travaux & BTP",
        "theme_labels": ["Travaux et Batiment", "Bricolage", "Plombier", "Serrurier", "Vitrier"],
    },
    {
        "macro_theme_label": "Finance / Assurance / Crédit",
        "theme_labels": ["Finance & Assurance", "Finance", "Assurance", "Crédits", "Banque"],
    },
    {
        "macro_theme_label": "Nature / Animaux / Écologie",
        "theme_labels": ["Animaux", "Environnement", "Écologie", "Bio", "Nature"],
    },
    {
        "macro_theme_label": "Auto / Transport",
        "theme_labels": ["Auto & Moto", "Transport & Véhicules"],
    },
    {
        "macro_theme_label": "Relations / Adulte / Ésotérisme",
        "theme_labels": [
            "Rencontre",
            "Plan cul",
            "Tchat, Dial & Webcam",
            "X (Adulte uniquement)",
            "Voyance",
        ],
    },
    {"macro_theme_label": "Immobilier", "theme_labels": ["Immobilier"]},
    {"macro_theme_label": "Gastronomie", "theme_labels": ["Gastronomie"]},
    {"macro_theme_label": "Famille", "theme_labels": ["Maman", "Bébé", "Mariage"]},
    {"macro_theme_label": "Inclassable", "theme_labels": ["Inclassable"]},
]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def slugify(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower().strip()
    )
    ascii_value = ascii_value.replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug or "sans-categorie"


def clean_theme(value: str) -> str:
    theme = " ".join((value or "").split()).strip()
    if theme == "- inclassable":
        return "Inclassable"
    return theme


def split_themes(value: str) -> list[str]:
    parts = [clean_theme(part) for part in (value or "").split("/")]
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        key = part.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(part)
    return deduped or ["Inclassable"]


def registered_domain(site_url: str) -> str:
    cleaned = (site_url or "").strip()
    if not cleaned:
        return ""
    host = cleaned
    if "://" in cleaned:
        host = urlsplit(cleaned).netloc
    host = host.split("@")[-1].split(":")[0].strip(".").lower()
    if tldextract is not None:
        extracted = tldextract.extract(host)
        domain = getattr(extracted, "top_domain_under_public_suffix", "")
        if domain:
            return domain.lower()
        if extracted.domain and extracted.suffix:
            return f"{extracted.domain}.{extracted.suffix}".lower()
    return host


def load_raw_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if (reader.fieldnames or []) != RAW_CATALOG_HEADERS:
            raise RuntimeError("Unexpected CSV headers in ereferer-bdd.csv")
        return list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_existing_site_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if (reader.fieldnames or []) != SITE_HEADERS:
            return {}
        rows = list(reader)
    existing: dict[str, dict[str, str]] = {}
    for row in rows:
        source_record_id = (row.get("source_record_id") or "").strip()
        site_id = (row.get("site_id") or "").strip()
        if source_record_id:
            existing[f"source:{source_record_id}"] = row
        if site_id:
            existing[f"site:{site_id}"] = row
    return existing


def build_macro_theme_maps() -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    macro_rows: list[dict[str, str]] = []
    macro_by_theme_label: dict[str, dict[str, str]] = {}
    seen_macro_labels: set[str] = set()
    seen_theme_labels: set[str] = set()

    for definition in MACRO_THEME_DEFINITIONS:
        macro_label = definition["macro_theme_label"]
        if macro_label in seen_macro_labels:
            raise RuntimeError(f"Duplicate macro theme label: {macro_label}")
        seen_macro_labels.add(macro_label)
        macro_slug = slugify(macro_label)
        macro_rows.append(
            {
                "macro_theme_slug": macro_slug,
                "macro_theme_label": macro_label,
                "enabled": "1",
                "default_cadence_days": "7",
                "priority": "normal",
            }
        )
        for theme_label in definition["theme_labels"]:
            if theme_label in seen_theme_labels:
                raise RuntimeError(f"Theme assigned to multiple macro themes: {theme_label}")
            seen_theme_labels.add(theme_label)
            macro_by_theme_label[theme_label] = {
                "macro_theme_slug": macro_slug,
                "macro_theme_label": macro_label,
            }

    return macro_rows, macro_by_theme_label


def build() -> int:
    root = repo_root()
    source_path = root / "ereferer-bdd.csv"
    if not source_path.exists():
        raise FileNotFoundError(f"Missing source file: {source_path}")

    rows = load_raw_rows(source_path)
    existing_site_rows = load_existing_site_rows(root / "catalog" / "sites.csv")

    theme_counts = Counter()
    themes_by_slug: dict[str, str] = {}
    site_rows: list[dict[str, object]] = []
    site_theme_rows: list[dict[str, object]] = []
    site_macro_theme_rows: list[dict[str, object]] = []
    macro_theme_rows, macro_by_theme_label = build_macro_theme_maps()

    for row in rows:
        site_id = f"eref-{row['id']}"
        themes = split_themes(row.get("categories_text", ""))
        primary = themes[0]
        site_macro_memberships: list[tuple[str, str]] = []
        seen_site_macro_slugs: set[str] = set()
        for position, theme_label in enumerate(themes, start=1):
            theme_slug = slugify(theme_label)
            themes_by_slug.setdefault(theme_slug, theme_label)
            theme_counts[theme_slug] += 1
            site_theme_rows.append(
                {
                    "site_id": site_id,
                    "theme_slug": theme_slug,
                    "theme_label": theme_label,
                    "theme_position": position,
                }
            )
            macro_theme = macro_by_theme_label.get(theme_label)
            if macro_theme is None:
                raise RuntimeError(f"Missing macro theme mapping for: {theme_label}")
            macro_theme_slug = macro_theme["macro_theme_slug"]
            if macro_theme_slug not in seen_site_macro_slugs:
                seen_site_macro_slugs.add(macro_theme_slug)
                site_macro_memberships.append(
                    (macro_theme_slug, macro_theme["macro_theme_label"])
                )

        for position, (macro_theme_slug, macro_theme_label) in enumerate(
            site_macro_memberships, start=1
        ):
            site_macro_theme_rows.append(
                {
                    "site_id": site_id,
                    "macro_theme_slug": macro_theme_slug,
                    "macro_theme_label": macro_theme_label,
                    "macro_theme_position": position,
                }
            )

        site_rows.append(
            {
                "site_id": site_id,
                "site": (row.get("url") or "").strip(),
                "name": (row.get("name") or "").strip(),
                "registered_domain": registered_domain(row.get("url", "")),
                "language": (row.get("language") or "").strip(),
                "source_record_id": row["id"],
                "sitemap": (
                    existing_site_rows.get(f"source:{row['id']}", {})
                    or existing_site_rows.get(f"site:{site_id}", {})
                ).get("sitemap", ""),
                "status": (
                    existing_site_rows.get(f"source:{row['id']}", {})
                    or existing_site_rows.get(f"site:{site_id}", {})
                ).get("status", "active"),
                "priority": (
                    existing_site_rows.get(f"source:{row['id']}", {})
                    or existing_site_rows.get(f"site:{site_id}", {})
                ).get("priority", "normal"),
                "cadence_days": (
                    existing_site_rows.get(f"source:{row['id']}", {})
                    or existing_site_rows.get(f"site:{site_id}", {})
                ).get("cadence_days", "7"),
                "theme_raw": (row.get("categories_text") or "").strip(),
                "theme_primary": primary,
                "price": (row.get("price") or "").strip(),
                "visits": (row.get("visits") or "").strip(),
                "unique_visitors": (row.get("unique_visitors") or "").strip(),
                "majestic_trust_flow": (row.get("majestic_trust_flow") or "").strip(),
                "majestic_ref_domains": (row.get("majestic_ref_domains") or "").strip(),
                "semrush_traffic": (row.get("semrush_traffic") or "").strip(),
                "moz_domain_authority": (row.get("moz_domain_authority") or "").strip(),
                "notes": (
                    existing_site_rows.get(f"source:{row['id']}", {})
                    or existing_site_rows.get(f"site:{site_id}", {})
                ).get("notes", ""),
            }
        )

    theme_rows = [
        {
            "theme_slug": slug,
            "theme_label": label,
            "enabled": "1",
            "default_cadence_days": "7",
            "priority": "normal",
        }
        for slug, label in sorted(themes_by_slug.items(), key=lambda item: item[1].casefold())
    ]

    missing_macro_assignments = [
        label
        for _, label in sorted(themes_by_slug.items(), key=lambda item: item[1].casefold())
        if label not in macro_by_theme_label
    ]
    if missing_macro_assignments:
        raise RuntimeError(
            "Missing macro theme mapping for: " + ", ".join(missing_macro_assignments)
        )

    theme_macro_map_rows = [
        {
            "theme_slug": slug,
            "theme_label": label,
            "macro_theme_slug": macro_by_theme_label[label]["macro_theme_slug"],
            "macro_theme_label": macro_by_theme_label[label]["macro_theme_label"],
        }
        for slug, label in sorted(themes_by_slug.items(), key=lambda item: item[1].casefold())
    ]

    theme_map_rows = [
        {
            "raw_theme": label,
            "theme_slug": slug,
            "theme_label": label,
            "macro_theme_slug": macro_by_theme_label[label]["macro_theme_slug"],
            "macro_theme_label": macro_by_theme_label[label]["macro_theme_label"],
            "enabled": "1",
            "default_cadence_days": "7",
            "priority": "normal",
        }
        for slug, label in sorted(themes_by_slug.items(), key=lambda item: item[1].casefold())
    ]

    write_csv(root / "catalog" / "themes.csv", THEME_HEADERS, theme_rows)
    write_csv(root / "catalog" / "macro_themes.csv", MACRO_THEME_HEADERS, macro_theme_rows)
    write_csv(root / "catalog" / "theme_macro_map.csv", THEME_MACRO_MAP_HEADERS, theme_macro_map_rows)
    write_csv(root / "catalog" / "theme_map.csv", THEME_MAP_HEADERS, theme_map_rows)
    write_csv(root / "catalog" / "sites.csv", SITE_HEADERS, site_rows)
    write_csv(root / "catalog" / "site_themes.csv", SITE_THEME_HEADERS, site_theme_rows)
    write_csv(
        root / "catalog" / "site_macro_themes.csv",
        SITE_MACRO_THEME_HEADERS,
        site_macro_theme_rows,
    )

    print(f"Imported {len(site_rows)} site(s)")
    print(f"Generated {len(theme_rows)} normalized theme(s)")
    print(f"Generated {len(macro_theme_rows)} macro theme(s)")
    print(f"Generated {len(site_theme_rows)} site/theme relation(s)")
    print(f"Generated {len(site_macro_theme_rows)} site/macro-theme relation(s)")
    print("Top 20 themes:")
    for slug, count in theme_counts.most_common(20):
        print(f"  {themes_by_slug[slug]} ({slug}): {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
