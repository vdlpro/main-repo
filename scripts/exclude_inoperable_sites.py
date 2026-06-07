from __future__ import annotations

import csv
from pathlib import Path


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

EXCLUDE_REASONS = {"http_403", "http_404", "no_sitemap_found", "invalid_sitemap_url"}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_site_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if (reader.fieldnames or []) != SITE_HEADERS:
            raise RuntimeError("Invalid headers in catalog/sites.csv")
        return list(reader)


def save_site_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SITE_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def load_latest_rejections(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    base_dir = repo_root()
    sites_path = base_dir / "catalog" / "sites.csv"
    rejections_path = base_dir / "data" / "state" / "rejections" / "latest.csv"

    site_rows = load_site_rows(sites_path)
    rejections = load_latest_rejections(rejections_path)
    if not rejections:
        print("No rejection rows found.")
        return 0

    rejection_by_site = {
        row["site_id"]: row
        for row in rejections
        if (row.get("decision") or "").strip() == "exclude_candidate"
        and (row.get("reason") or "").strip() in EXCLUDE_REASONS
    }
    changed = 0
    for row in site_rows:
        site_id = row["site_id"]
        rejection = rejection_by_site.get(site_id)
        if not rejection:
            continue
        if row.get("status") == "invalid":
            continue
        row["status"] = "invalid"
        reason = rejection["reason"]
        detail = f"sitemap_excluded:{reason}"
        existing_notes = (row.get("notes") or "").strip()
        row["notes"] = detail if not existing_notes else f"{existing_notes} | {detail}"
        changed += 1

    if changed:
        save_site_rows(sites_path, site_rows)
    print(f"Excluded {changed} site(s) by marking them invalid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
