from __future__ import annotations

import csv
import gzip
import json
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path


REQUIRED_THEME_HEADERS = [
    "theme_slug",
    "theme_label",
    "enabled",
    "default_cadence_days",
    "priority",
]

REQUIRED_MACRO_THEME_HEADERS = [
    "macro_theme_slug",
    "macro_theme_label",
    "enabled",
    "default_cadence_days",
    "priority",
]

REQUIRED_SITE_HEADERS = [
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

REQUIRED_SITE_THEME_HEADERS = [
    "site_id",
    "theme_slug",
    "theme_label",
    "theme_position",
]

REQUIRED_SITE_MACRO_THEME_HEADERS = [
    "site_id",
    "macro_theme_slug",
    "macro_theme_label",
    "macro_theme_position",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: object) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_headers(path: Path, expected: list[str]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if (reader.fieldnames or []) != expected:
            raise RuntimeError(
                f"Invalid headers in {path.name}. Expected exactly: {', '.join(expected)}"
            )


def load_jsonl_gz(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def active_rows(rows: list[dict[str, str]], key: str = "enabled", value: str = "1") -> list[dict[str, str]]:
    return [row for row in rows if (row.get(key) or "").strip() == value]


def active_sites(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if (row.get("status") or "").strip() == "active"]


def to_int(value: str | int | float | None) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    cleaned = str(value).strip().replace(" ", "")
    if not cleaned:
        return 0
    try:
        return int(float(cleaned.replace(",", ".")))
    except ValueError:
        return 0


IGNORED_TARGET_DOMAINS = {"mag-du-web.fr", "t.co", "x.com"}
IGNORED_TARGET_DOMAIN_LABELS = {
    "amazon",
    "example",
    "facebook",
    "google",
    "instagram",
    "linkedin",
    "microsoft",
    "openai",
    "perplexity",
    "pinterest",
    "twitter",
    "whatsapp",
    "youtube",
}


def should_ignore_target_domain(target_domain: str) -> bool:
    normalized = (target_domain or "").strip().lower()
    if not normalized:
        return True
    if normalized in IGNORED_TARGET_DOMAINS:
        return True
    return normalized.split(".", 1)[0] in IGNORED_TARGET_DOMAIN_LABELS


def build_seller_row(
    site_row: dict[str, str],
    page_events: list[dict[str, object]],
    link_events: list[dict[str, object]],
    site_theme_rows: list[dict[str, str]],
    site_macro_rows: list[dict[str, str]],
    scope_kind: str,
    scope_slug: str,
) -> dict[str, object]:
    unique_target_domains = sorted({str(link["target_domain"]) for link in link_events})
    raw_links = sum(to_int(event.get("raw_outgoing_links_count")) for event in page_events)
    unique_targets_total = sum(
        to_int(event.get("unique_target_domains_count")) for event in page_events
    )
    articles_with_links = sum(
        1 for event in page_events if to_int(event.get("raw_outgoing_links_count")) > 0
    )
    return {
        "domain": site_row["registered_domain"],
        "site": site_row["site"],
        "name": site_row["name"],
        "articles_analyzed": len(page_events),
        "articles_with_external_links": articles_with_links,
        "raw_outgoing_links_count": raw_links,
        "unique_target_domains_count": len(unique_target_domains),
        "avg_raw_links_per_article": round(raw_links / len(page_events), 2) if page_events else 0,
        "avg_unique_target_domains_per_article": round(
            unique_targets_total / len(page_events), 2
        )
        if page_events
        else 0,
        "visits": to_int(site_row.get("visits")),
        "traffic_google": to_int(site_row.get("semrush_traffic")),
        "tf": to_int(site_row.get("majestic_trust_flow")),
        "rd": to_int(site_row.get("majestic_ref_domains")),
        "da": to_int(site_row.get("moz_domain_authority")),
        "scope_kind": scope_kind,
        "scope_slug": scope_slug,
        "theme_primary": site_row.get("theme_primary", ""),
        "theme_raw": site_row.get("theme_raw", ""),
        "themes": [row["theme_slug"] for row in site_theme_rows],
        "theme_labels": [row["theme_label"] for row in site_theme_rows],
        "macro_themes": [row["macro_theme_slug"] for row in site_macro_rows],
        "macro_theme_labels": [row["macro_theme_label"] for row in site_macro_rows],
    }


def build_scope_payload(
    scope_kind: str,
    scope_slug: str,
    scope_label: str,
    seller_sites: list[dict[str, str]],
    site_themes_by_site: dict[str, list[dict[str, str]]],
    site_macros_by_site: dict[str, list[dict[str, str]]],
    pages_by_site: dict[str, list[dict[str, object]]],
    links_by_site: dict[str, list[dict[str, object]]],
    catalog_by_domain: dict[str, dict[str, str]],
) -> dict[str, object]:
    site_ids = {row["site_id"] for row in seller_sites}
    filtered_page_events: list[dict[str, object]] = []
    filtered_link_events: list[dict[str, object]] = []
    for site_id in site_ids:
        filtered_page_events.extend(pages_by_site.get(site_id, []))
        filtered_link_events.extend(links_by_site.get(site_id, []))

    sellers_summary = [
        build_seller_row(
            site_row,
            pages_by_site.get(site_row["site_id"], []),
            links_by_site.get(site_row["site_id"], []),
            site_themes_by_site.get(site_row["site_id"], []),
            site_macros_by_site.get(site_row["site_id"], []),
            scope_kind,
            scope_slug,
        )
        for site_row in sorted(seller_sites, key=lambda row: (row["registered_domain"], row["site"]))
    ]

    buyers_by_domain: dict[str, dict[str, object]] = {}
    edge_map: dict[tuple[str, str], dict[str, object]] = {}
    for link in filtered_link_events:
        target_domain = str(link["target_domain"])
        source_domain = str(link["source_domain"])
        target = buyers_by_domain.setdefault(
            target_domain,
            {
                "target_domain": target_domain,
                "links_count": 0,
                "source_domains": set(),
                "source_pages": set(),
            },
        )
        target["links_count"] += 1
        target["source_domains"].add(source_domain)
        target["source_pages"].add(str(link["source_url"]))

        edge_key = (source_domain, target_domain)
        edge = edge_map.setdefault(
            edge_key,
            {
                "source_domain": source_domain,
                "target_domain": target_domain,
                "links_count": 0,
                "source_pages": set(),
                "first_seen": str(link["detected_on"]),
                "last_seen": str(link["detected_on"]),
            },
        )
        edge["links_count"] += 1
        edge["source_pages"].add(str(link["source_url"]))
        if str(link["detected_on"]) < edge["first_seen"]:
            edge["first_seen"] = str(link["detected_on"])
        if str(link["detected_on"]) > edge["last_seen"]:
            edge["last_seen"] = str(link["detected_on"])

    buyers_summary: list[dict[str, object]] = []
    for target_domain, stats in sorted(
        buyers_by_domain.items(),
        key=lambda item: (-int(item[1]["links_count"]), item[0]),
    ):
        catalog_row = catalog_by_domain.get(target_domain, {})
        buyers_summary.append(
            {
                "target_domain": target_domain,
                "links_count": int(stats["links_count"]),
                "source_domains_count": len(stats["source_domains"]),
                "source_pages_count": len(stats["source_pages"]),
                "visits": to_int(catalog_row.get("visits")),
                "traffic_google": to_int(catalog_row.get("semrush_traffic")),
                "tf": to_int(catalog_row.get("majestic_trust_flow")),
                "rd": to_int(catalog_row.get("majestic_ref_domains")),
                "da": to_int(catalog_row.get("moz_domain_authority")),
            }
        )

    network_edges = sorted(
        [
            {
                "source_domain": edge["source_domain"],
                "target_domain": edge["target_domain"],
                "links_count": int(edge["links_count"]),
                "source_pages_count": len(edge["source_pages"]),
                "first_seen": edge["first_seen"],
                "last_seen": edge["last_seen"],
            }
            for edge in edge_map.values()
        ],
        key=lambda item: (-int(item["links_count"]), item["source_domain"], item["target_domain"]),
    )

    links_recent = sorted(
        [
            {
                "published_at": str(link["detected_on"]),
                "source_domain": str(link["source_domain"]),
                "source_url": str(link["source_url"]),
                "target_domain": str(link["target_domain"]),
                "target_url": str(link["target_url"]),
                "anchor": str(link.get("anchor_text", "")),
                "link_type": "follow" if bool(link.get("is_follow")) else "nofollow",
            }
            for link in filtered_link_events
        ],
        key=lambda item: (
            item["published_at"],
            item["source_domain"],
            item["target_domain"],
            item["source_url"],
        ),
        reverse=True,
    )[:1000]

    return {
        "build_meta.json": {
            "generated_on": str(date.today()),
            "scope_kind": scope_kind,
            "scope_slug": scope_slug,
            "scope_label": scope_label,
            "seller_count": len(seller_sites),
            "buyer_count": len(buyers_summary),
            "page_events_count": len(filtered_page_events),
            "link_events_count": len(filtered_link_events),
        },
        "sellers_summary.json": sellers_summary,
        "buyers_summary.json": buyers_summary,
        "links_recent.json": links_recent,
        "network_edges.json": network_edges,
    }


def build() -> int:
    root = repo_root()
    catalog_dir = root / "catalog"
    public_data_dir = root / "public" / "data"
    events_pages_dir = root / "data" / "events" / "pages"
    events_links_dir = root / "data" / "events" / "links"

    themes_path = catalog_dir / "themes.csv"
    macro_themes_path = catalog_dir / "macro_themes.csv"
    sites_path = catalog_dir / "sites.csv"
    site_themes_path = catalog_dir / "site_themes.csv"
    site_macro_themes_path = catalog_dir / "site_macro_themes.csv"

    validate_headers(themes_path, REQUIRED_THEME_HEADERS)
    validate_headers(macro_themes_path, REQUIRED_MACRO_THEME_HEADERS)
    validate_headers(sites_path, REQUIRED_SITE_HEADERS)
    validate_headers(site_themes_path, REQUIRED_SITE_THEME_HEADERS)
    validate_headers(site_macro_themes_path, REQUIRED_SITE_MACRO_THEME_HEADERS)

    _themes = active_rows(load_csv(themes_path))
    macro_themes = active_rows(load_csv(macro_themes_path))
    sites = active_sites(load_csv(sites_path))
    site_themes = load_csv(site_themes_path)
    site_macro_themes = load_csv(site_macro_themes_path)

    site_by_id = {row["site_id"]: row for row in sites}
    catalog_by_domain: dict[str, dict[str, str]] = {}
    for row in sites:
        catalog_by_domain.setdefault(row["registered_domain"], row)

    site_themes_by_site: dict[str, list[dict[str, str]]] = defaultdict(list)
    site_macros_by_site: dict[str, list[dict[str, str]]] = defaultdict(list)
    site_ids_by_macro: dict[str, set[str]] = defaultdict(set)
    for row in site_themes:
        if row["site_id"] in site_by_id:
            site_themes_by_site[row["site_id"]].append(row)
    for row in site_macro_themes:
        if row["site_id"] in site_by_id:
            site_macros_by_site[row["site_id"]].append(row)
            site_ids_by_macro[row["macro_theme_slug"]].add(row["site_id"])

    page_events: list[dict[str, object]] = []
    link_events: list[dict[str, object]] = []
    for path in sorted(events_pages_dir.glob("*.jsonl.gz")):
        page_events.extend(load_jsonl_gz(path))
    for path in sorted(events_links_dir.glob("*.jsonl.gz")):
        link_events.extend(load_jsonl_gz(path))

    page_events = [event for event in page_events if str(event.get("site_id", "")) in site_by_id]
    link_events = [
        event
        for event in link_events
        if str(event.get("site_id", "")) in site_by_id
        and not should_ignore_target_domain(str(event.get("target_domain", "")))
        and str(event.get("anchor_text", "")).strip()
    ]

    pages_by_site: dict[str, list[dict[str, object]]] = defaultdict(list)
    links_by_site: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in page_events:
        pages_by_site[str(event["site_id"])].append(event)
    for event in link_events:
        links_by_site[str(event["site_id"])].append(event)

    all_dir = public_data_dir / "all"
    macros_dir = public_data_dir / "macros"
    legacy_themes_dir = public_data_dir / "themes"
    reset_dir(all_dir)
    reset_dir(macros_dir)
    if legacy_themes_dir.exists():
        shutil.rmtree(legacy_themes_dir)

    global_payload = build_scope_payload(
        "all",
        "all",
        "Toutes thématiques",
        sites,
        site_themes_by_site,
        site_macros_by_site,
        pages_by_site,
        links_by_site,
        catalog_by_domain,
    )
    for name, content in global_payload.items():
        write_json(all_dir / name, content)

    manifest_macros: list[dict[str, object]] = []
    for macro in macro_themes:
        slug = macro["macro_theme_slug"]
        label = macro["macro_theme_label"]
        macro_sites = [site_by_id[site_id] for site_id in sorted(site_ids_by_macro.get(slug, set()))]
        payload = build_scope_payload(
            "macro_theme",
            slug,
            label,
            macro_sites,
            site_themes_by_site,
            site_macros_by_site,
            pages_by_site,
            links_by_site,
            catalog_by_domain,
        )
        macro_dir = macros_dir / slug
        for name, content in payload.items():
            write_json(macro_dir / name, content)
        manifest_macros.append(
            {
                "macro_theme_slug": slug,
                "macro_theme_label": label,
                "enabled": True,
                "seller_count": payload["build_meta.json"]["seller_count"],
                "paths": {
                    "build_meta": f"./macros/{slug}/build_meta.json",
                    "sellers_summary": f"./macros/{slug}/sellers_summary.json",
                    "buyers_summary": f"./macros/{slug}/buyers_summary.json",
                    "links_recent": f"./macros/{slug}/links_recent.json",
                    "network_edges": f"./macros/{slug}/network_edges.json",
                },
            }
        )

    write_json(
        public_data_dir / "manifest.json",
        {
            "generated_on": str(date.today()),
            "theme_count": len(_themes),
            "macro_theme_count": len(manifest_macros),
            "seller_count": len(sites),
            "theme_memberships_count": len(site_themes),
            "macro_theme_memberships_count": len(site_macro_themes),
            "macros": manifest_macros,
            "all": {
                "build_meta": "./all/build_meta.json",
                "sellers_summary": "./all/sellers_summary.json",
                "buyers_summary": "./all/buyers_summary.json",
                "links_recent": "./all/links_recent.json",
                "network_edges": "./all/network_edges.json",
            },
        },
    )

    print(f"Generated manifest for {len(manifest_macros)} macro theme(s)")
    print(f"Global sellers: {len(global_payload['sellers_summary.json'])}")
    print(f"Global buyers: {len(global_payload['buyers_summary.json'])}")
    print(f"Global links: {len(global_payload['links_recent.json'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
