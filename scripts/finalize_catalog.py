from __future__ import annotations

import csv
import shutil
from pathlib import Path

from import_ereferer_catalog import (
    MACRO_THEME_HEADERS,
    SITE_HEADERS,
    SITE_MACRO_THEME_HEADERS,
    SITE_THEME_HEADERS,
    THEME_HEADERS,
    THEME_MACRO_MAP_HEADERS,
    THEME_MAP_HEADERS,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def finalize() -> int:
    root = repo_root()
    catalog_dir = root / "catalog"
    state_dir = root / "data" / "state"
    events_dir = root / "data" / "events"
    public_data_dir = root / "public" / "data"

    site_rows = load_csv(catalog_dir / "sites.csv")
    site_theme_rows = load_csv(catalog_dir / "site_themes.csv")
    site_macro_rows = load_csv(catalog_dir / "site_macro_themes.csv")
    theme_rows = load_csv(catalog_dir / "themes.csv")
    macro_theme_rows = load_csv(catalog_dir / "macro_themes.csv")
    theme_map_rows = load_csv(catalog_dir / "theme_map.csv")
    theme_macro_map_rows = load_csv(catalog_dir / "theme_macro_map.csv")

    active_sites: list[dict[str, str]] = []
    for row in site_rows:
        if (row.get("status") or "").strip() != "active":
            continue
        if not (row.get("site") or "").strip():
            continue
        if not (row.get("registered_domain") or "").strip():
            continue
        if not (row.get("sitemap") or "").strip():
            continue
        row = dict(row)
        row["status"] = "active"
        active_sites.append(row)

    active_site_ids = {row["site_id"] for row in active_sites}

    filtered_site_themes = [
        row for row in site_theme_rows if (row.get("site_id") or "").strip() in active_site_ids
    ]
    filtered_site_macros = [
        row for row in site_macro_rows if (row.get("site_id") or "").strip() in active_site_ids
    ]

    used_theme_slugs = {
        (row.get("theme_slug") or "").strip() for row in filtered_site_themes if row.get("theme_slug")
    }
    used_macro_slugs = {
        (row.get("macro_theme_slug") or "").strip()
        for row in filtered_site_macros
        if row.get("macro_theme_slug")
    }

    filtered_themes = [
        row for row in theme_rows if (row.get("theme_slug") or "").strip() in used_theme_slugs
    ]
    filtered_macro_themes = [
        row
        for row in macro_theme_rows
        if (row.get("macro_theme_slug") or "").strip() in used_macro_slugs
    ]
    filtered_theme_map = [
        row for row in theme_map_rows if (row.get("theme_slug") or "").strip() in used_theme_slugs
    ]
    filtered_theme_macro_map = [
        row
        for row in theme_macro_map_rows
        if (row.get("theme_slug") or "").strip() in used_theme_slugs
    ]

    write_csv(catalog_dir / "sites.csv", SITE_HEADERS, active_sites)
    write_csv(catalog_dir / "site_themes.csv", SITE_THEME_HEADERS, filtered_site_themes)
    write_csv(
        catalog_dir / "site_macro_themes.csv",
        SITE_MACRO_THEME_HEADERS,
        filtered_site_macros,
    )
    write_csv(catalog_dir / "themes.csv", THEME_HEADERS, filtered_themes)
    write_csv(catalog_dir / "macro_themes.csv", MACRO_THEME_HEADERS, filtered_macro_themes)
    write_csv(catalog_dir / "theme_map.csv", THEME_MAP_HEADERS, filtered_theme_map)
    write_csv(
        catalog_dir / "theme_macro_map.csv",
        THEME_MACRO_MAP_HEADERS,
        filtered_theme_macro_map,
    )

    # Keep sitemap audit artefacts, but reset runtime crawl state for a clean incremental baseline.
    reset_dir(state_dir / "snapshots")
    reset_dir(state_dir / "ever_seen")
    reset_dir(state_dir / "sites")
    reset_dir(state_dir / "rejections")
    reset_dir(state_dir / "runtime")
    reset_dir(events_dir / "pages")
    reset_dir(events_dir / "links")
    reset_dir(public_data_dir / "all")
    reset_dir(public_data_dir / "macros")
    remove_file(public_data_dir / "manifest.json")

    print(f"Active sites kept: {len(active_sites)}")
    print(f"Theme memberships kept: {len(filtered_site_themes)}")
    print(f"Macro theme memberships kept: {len(filtered_site_macros)}")
    print("Runtime crawl state reset for fresh incremental baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(finalize())
