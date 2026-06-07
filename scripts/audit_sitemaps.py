from __future__ import annotations

import csv
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from crawl_v2 import (
    SITEMAP_TIMEOUT,
    SiteRecord,
    catalog_sites_path,
    crawler_decision_for_reason,
    discover_sitemap,
    load_sites,
    log_info,
    log_warn,
    parse_sitemap,
    session_with_headers,
)


BATCH_INDEX = int(os.getenv("AUDIT_BATCH_INDEX", "1"))
BATCH_SIZE = int(os.getenv("AUDIT_BATCH_SIZE", "2000"))
BATCH_START_POSITION = int(os.getenv("AUDIT_BATCH_START_POSITION", "0"))
BATCH_KEY = (os.getenv("AUDIT_BATCH_KEY", "") or "").strip()
SITE_IDS_FILE = (os.getenv("AUDIT_SITE_IDS_FILE", "") or "").strip()
EXCLUDE_ON_FAILURE = (os.getenv("AUDIT_EXCLUDE_ON_FAILURE", "0") or "").strip() == "1"
AUDIT_WORKERS = int(os.getenv("AUDIT_WORKERS", "24"))
AUDIT_SITE_BUDGET_SECONDS = int(os.getenv("AUDIT_SITE_BUDGET_SECONDS", "60"))
SECOND_PASS_TIMEOUT = int(os.getenv("AUDIT_SECOND_PASS_TIMEOUT", "40"))
SECOND_PASS_WORKERS = int(os.getenv("AUDIT_SECOND_PASS_WORKERS", "8"))
PROGRESS_EVERY = int(os.getenv("AUDIT_PROGRESS_EVERY", "50"))
CHECKPOINT_EVERY = int(os.getenv("AUDIT_CHECKPOINT_EVERY", "25"))

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

CSV_HEADERS = [
    "batch_index",
    "batch_size",
    "site_position",
    "site_id",
    "site",
    "domain",
    "previous_sitemap",
    "sitemap_url",
    "discovery_stage",
    "reason",
    "decision",
    "crawl_complete",
    "urls_count",
    "pass_name",
    "checked",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def audit_dir(base_dir: Path) -> Path:
    return base_dir / "data" / "state" / "sitemap_audit"


def effective_batch_key() -> str:
    return BATCH_KEY or f"{BATCH_INDEX:04d}"


def batch_csv_path(base_dir: Path, batch_key: str) -> Path:
    return audit_dir(base_dir) / "batches" / f"batch-{batch_key}.csv"


def latest_csv_path(base_dir: Path) -> Path:
    return audit_dir(base_dir) / "latest.csv"


def summary_json_path(base_dir: Path, batch_key: str) -> Path:
    return audit_dir(base_dir) / "summaries" / f"batch-{batch_key}.json"


def checkpoint_json_path(base_dir: Path, batch_key: str) -> Path:
    return audit_dir(base_dir) / "checkpoints" / f"batch-{batch_key}.json"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CSV_HEADERS})


def write_summary(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_checkpoint(
    path: Path,
    pass_1_rows: dict[str, dict[str, object]],
    pass_2_rows: dict[str, dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "pass_1_rows": pass_1_rows,
        "pass_2_rows": pass_2_rows,
    }
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def load_checkpoint(path: Path) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    if not path.exists():
        return {}, {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    pass_1_rows = payload.get("pass_1_rows") or {}
    pass_2_rows = payload.get("pass_2_rows") or {}
    if not isinstance(pass_1_rows, dict) or not isinstance(pass_2_rows, dict):
        return {}, {}
    return pass_1_rows, pass_2_rows


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


def load_selected_site_ids(path: str) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Missing site ids file: {file_path}")
    values: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        values.append(line)
    return values


def update_found_sitemaps(base_dir: Path, results: list[dict[str, object]]) -> int:
    path = catalog_sites_path(base_dir)
    rows = load_site_rows(path)
    by_site_id = {row["site_id"]: row for row in rows}
    changed = 0
    for result in results:
        if result.get("decision") != "ok":
            continue
        sitemap_url = str(result.get("sitemap_url") or "").strip()
        if not sitemap_url:
            continue
        row = by_site_id.get(str(result["site_id"]))
        if row is None:
            continue
        if row.get("sitemap") == sitemap_url:
            continue
        row["sitemap"] = sitemap_url
        changed += 1
    if changed:
        save_site_rows(path, rows)
    return changed


def exclude_failed_sites(base_dir: Path, results: list[dict[str, object]], batch_key: str) -> int:
    failing_site_ids = {
        str(row["site_id"])
        for row in results
        if row.get("decision") != "ok"
    }
    if not failing_site_ids:
        return 0

    path = catalog_sites_path(base_dir)
    rows = load_site_rows(path)
    changed = 0
    for row in rows:
        if row["site_id"] not in failing_site_ids:
            continue
        if row.get("status") == "excluded":
            continue
        row["status"] = "excluded"
        existing_notes = (row.get("notes") or "").strip()
        note = f"excluded_after_reaudit:{batch_key}"
        row["notes"] = f"{existing_notes} | {note}".strip(" |") if existing_notes else note
        changed += 1
    if changed:
        save_site_rows(path, rows)
    return changed


def materialize_rows(
    pass_1_rows: dict[str, dict[str, object]],
    pass_2_rows: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    final_by_site_id = dict(pass_1_rows)
    final_by_site_id.update(pass_2_rows)
    return sorted(final_by_site_id.values(), key=lambda row: int(row["site_position"]))


def persist_progress(
    base_dir: Path,
    batch_key: str,
    batch_index: int,
    batch_size: int,
    batch_start: int,
    batch_end: int,
    total_sites: int,
    pass_1_rows: dict[str, dict[str, object]],
    pass_2_rows: dict[str, dict[str, object]],
    done: bool,
) -> None:
    final_rows = materialize_rows(pass_1_rows, pass_2_rows)
    write_checkpoint(checkpoint_json_path(base_dir, batch_key), pass_1_rows, pass_2_rows)
    write_csv(batch_csv_path(base_dir, batch_key), final_rows)
    write_csv(latest_csv_path(base_dir), final_rows)

    summary = summarize(final_rows)
    summary.update(
        {
            "batch_key": batch_key,
            "batch_index": batch_index,
            "batch_size": batch_size,
            "site_start": batch_start + 1,
            "site_end": batch_end,
            "total_sites": total_sites,
            "workers_pass_1": AUDIT_WORKERS,
            "workers_pass_2": SECOND_PASS_WORKERS,
            "timeout_pass_1": SITEMAP_TIMEOUT,
            "timeout_pass_2": SECOND_PASS_TIMEOUT,
            "updated_sitemaps_in_catalog": 0,
            "checkpointed": True,
            "done": done,
        }
    )
    write_summary(summary_json_path(base_dir, batch_key), summary)


def scan_site(site: SiteRecord, timeout: int) -> tuple[SiteRecord, str, str, str, int, bool, list[str]]:
    session = session_with_headers()
    try:
        deadline = time.monotonic() + max(1, AUDIT_SITE_BUDGET_SECONDS)
        sitemap_url, discovery_stage, checked = discover_sitemap(
            session,
            site,
            timeout=timeout,
            deadline=deadline,
        )
        if not sitemap_url:
            return site, "", discovery_stage, discovery_stage, 0, False, checked
        current_urls, crawl_complete, reason = parse_sitemap(
            session,
            sitemap_url,
            timeout=timeout,
            deadline=deadline,
            documents_seen=[0],
        )
        return site, sitemap_url, discovery_stage, reason, len(current_urls), crawl_complete, checked
    finally:
        session.close()


def choose_retry(site_result: dict[str, object]) -> bool:
    if bool(site_result.get("crawl_complete")):
        return False
    reason = str(site_result.get("reason") or "")
    return reason in {
        "timeout",
        "connectionerror",
        "sslerror",
        "chunkedencodingerror",
        "http_408",
        "http_425",
        "http_429",
        "http_500",
        "http_502",
        "http_503",
        "http_504",
        "invalid_xml",
        "unsupported_xml_root",
    }


def run_pass(
    sites: list[SiteRecord],
    workers: int,
    timeout: int,
    pass_name: str,
    batch_index: int,
    batch_size: int,
    site_offset: int,
    existing_rows: dict[str, dict[str, object]] | None = None,
    on_checkpoint=None,
) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = dict(existing_rows or {})
    site_positions = {str(site.site_id): idx for idx, site in enumerate(sites, start=site_offset + 1)}
    pending_sites = [site for site in sites if str(site.site_id) not in results]
    if not pending_sites:
        log_info(f"Audit {pass_name}: reprise, rien à recalculer")
        return results

    total = len(pending_sites)
    completed = 0
    log_info(
        f"Audit {pass_name}: {len(pending_sites)}/{len(sites)} site(s) à traiter, "
        f"{workers} worker(s), timeout {timeout}s"
    )
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_to_meta = {
            executor.submit(scan_site, site, timeout): (site_positions[str(site.site_id)], site)
            for site in pending_sites
        }
        for future in as_completed(future_to_meta):
            position, site = future_to_meta[future]
            try:
                site, sitemap_url, discovery_stage, reason, urls_count, crawl_complete, checked = future.result()
            except Exception as exc:
                sitemap_url = site.sitemap
                discovery_stage = "exception"
                reason = exc.__class__.__name__.lower()
                urls_count = 0
                crawl_complete = False
                checked = [site.site]
                log_warn(f"Audit {pass_name} unexpected failure for {site.registered_domain} ({exc})")

            decision = "ok" if crawl_complete and sitemap_url and urls_count > 0 else crawler_decision_for_reason(reason)
            results[str(site.site_id)] = {
                "batch_index": batch_index,
                "batch_size": batch_size,
                "site_position": position,
                "site_id": site.site_id,
                "site": site.site,
                "domain": site.registered_domain,
                "previous_sitemap": site.sitemap,
                "sitemap_url": sitemap_url,
                "discovery_stage": discovery_stage,
                "reason": reason,
                "decision": decision,
                "crawl_complete": crawl_complete,
                "urls_count": urls_count,
                "pass_name": pass_name,
                "checked": "; ".join(checked[:30]),
            }
            completed += 1
            if completed % PROGRESS_EVERY == 0 or completed == total:
                log_info(f"Audit {pass_name}: {completed}/{total}")
            if on_checkpoint and (
                completed % max(1, CHECKPOINT_EVERY) == 0 or completed == total
            ):
                on_checkpoint(results)
    return results


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    summary: dict[str, object] = {
        "rows": len(rows),
        "ok": sum(1 for row in rows if row["decision"] == "ok"),
        "exclude_candidate": sum(1 for row in rows if row["decision"] == "exclude_candidate"),
        "retry_later": sum(1 for row in rows if row["decision"] == "retry_later"),
        "reasons": {},
    }
    reason_counts: dict[str, int] = {}
    for row in rows:
        reason = str(row["reason"])
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    summary["reasons"] = dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])))
    return summary


def main() -> int:
    base_dir = repo_root()
    batch_key = effective_batch_key()
    all_sites = [site for site in load_sites(base_dir) if site.status == "active"]
    all_sites.sort(key=lambda site: (site.registered_domain, site.site_id))
    total_sites = len(all_sites)

    if SITE_IDS_FILE:
        selected_ids = load_selected_site_ids(SITE_IDS_FILE)
        selected_set = set(selected_ids)
        batch_sites = [site for site in all_sites if site.site_id in selected_set]
        missing_ids = selected_set - {site.site_id for site in batch_sites}
        if missing_ids:
            log_warn(f"{len(missing_ids)} site_id introuvable(s) ou non actifs ignorés")
        batch_sites.sort(key=lambda site: selected_ids.index(site.site_id) if site.site_id in selected_set else 10**9)
        batch_start = 0
        batch_end = len(batch_sites)
        effective_batch_size = len(batch_sites)
    elif BATCH_START_POSITION > 0:
        batch_start = max(0, BATCH_START_POSITION - 1)
        batch_end = min(total_sites, batch_start + BATCH_SIZE)
        batch_sites = all_sites[batch_start:batch_end]
        effective_batch_size = BATCH_SIZE
    else:
        batch_start = max(0, (BATCH_INDEX - 1) * BATCH_SIZE)
        batch_end = min(total_sites, batch_start + BATCH_SIZE)
        batch_sites = all_sites[batch_start:batch_end]
        effective_batch_size = BATCH_SIZE

    if not batch_sites:
        raise RuntimeError(f"No sites for batch {batch_key}")

    pass_1_rows, pass_2_rows = load_checkpoint(checkpoint_json_path(base_dir, batch_key))

    log_info(
        f"Audit batch {batch_key}: "
        f"{'selection explicite' if SITE_IDS_FILE else f'sites {batch_start + 1}-{batch_end}/{total_sites}'} "
        f"with {AUDIT_WORKERS} workers"
    )

    def checkpoint_after_pass_1(current_pass_1_rows: dict[str, dict[str, object]]) -> None:
        persist_progress(
            base_dir,
            batch_key,
            BATCH_INDEX,
            effective_batch_size,
            batch_start,
            batch_end,
            total_sites,
            current_pass_1_rows,
            pass_2_rows,
            done=False,
        )

    pass_1_rows = run_pass(
        batch_sites,
        AUDIT_WORKERS,
        SITEMAP_TIMEOUT,
        "pass-1",
        BATCH_INDEX,
        effective_batch_size,
        batch_start,
        existing_rows=pass_1_rows,
        on_checkpoint=checkpoint_after_pass_1,
    )

    retry_sites = [
        next(site for site in batch_sites if site.site_id == row["site_id"])
        for row in pass_1_rows.values()
        if choose_retry(row)
    ]

    if retry_sites:
        def checkpoint_after_pass_2(current_pass_2_rows: dict[str, dict[str, object]]) -> None:
            persist_progress(
                base_dir,
                batch_key,
                BATCH_INDEX,
                effective_batch_size,
                batch_start,
                batch_end,
                total_sites,
                pass_1_rows,
                current_pass_2_rows,
                done=False,
            )

        pass_2_rows = run_pass(
            retry_sites,
            SECOND_PASS_WORKERS,
            SECOND_PASS_TIMEOUT,
            "pass-2",
            BATCH_INDEX,
            effective_batch_size,
            batch_start,
            existing_rows=pass_2_rows,
            on_checkpoint=checkpoint_after_pass_2,
        )

    final_rows = materialize_rows(pass_1_rows, pass_2_rows)
    found_updates = update_found_sitemaps(base_dir, final_rows)
    excluded_after_reaudit = 0
    if EXCLUDE_ON_FAILURE:
        excluded_after_reaudit = exclude_failed_sites(base_dir, final_rows, batch_key)

    write_csv(batch_csv_path(base_dir, batch_key), final_rows)
    write_csv(latest_csv_path(base_dir), final_rows)
    summary = summarize(final_rows)
    summary.update(
        {
            "batch_key": batch_key,
            "batch_index": BATCH_INDEX,
            "batch_size": effective_batch_size,
            "site_start": batch_start + 1,
            "site_end": batch_end,
            "total_sites": total_sites,
            "workers_pass_1": AUDIT_WORKERS,
            "workers_pass_2": SECOND_PASS_WORKERS,
            "timeout_pass_1": SITEMAP_TIMEOUT,
            "timeout_pass_2": SECOND_PASS_TIMEOUT,
            "updated_sitemaps_in_catalog": found_updates,
            "excluded_after_reaudit": excluded_after_reaudit,
            "checkpointed": True,
            "done": True,
        }
    )
    write_summary(summary_json_path(base_dir, batch_key), summary)

    log_info(
        f"Audit batch {batch_key} done: ok={summary['ok']}, "
        f"exclude_candidate={summary['exclude_candidate']}, retry_later={summary['retry_later']}, "
        f"sitemaps_updated={found_updates}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
