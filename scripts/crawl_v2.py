from __future__ import annotations

import csv
import gzip
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import requests
import tldextract
from bs4 import BeautifulSoup


USER_AGENT = "Mozilla/5.0 (compatible; AnalyseFullEreferer/1.0; +https://github.com/)"
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
SITEMAP_TIMEOUT = int(os.getenv("SITEMAP_TIMEOUT", "20"))
SITEMAP_CONNECT_TIMEOUT = int(os.getenv("SITEMAP_CONNECT_TIMEOUT", "8"))
PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "20"))
SITEMAP_WORKERS = int(os.getenv("SITEMAP_WORKERS", "12"))
PAGE_WORKERS = int(os.getenv("PAGE_WORKERS", "16"))
PROGRESS_EVERY = int(os.getenv("PROGRESS_EVERY", "25"))
MAX_SITES_OVERRIDE_RAW = os.getenv("MAX_SITES_OVERRIDE")
MAX_INITIAL_URLS_PER_SITE = int(os.getenv("MAX_INITIAL_URLS_PER_SITE", "3"))
MAX_NEW_URLS_PER_SITE = int(os.getenv("MAX_NEW_URLS_PER_SITE", "100"))
MAX_SITEMAP_DOCUMENTS = int(os.getenv("MAX_SITEMAP_DOCUMENTS", "120"))
SEED_INITIAL_URLS = (os.getenv("SEED_INITIAL_URLS", "0") or "").strip() == "1"
RUN_BUDGET_SECONDS = int(os.getenv("RUN_BUDGET_SECONDS", "18000"))
RUN_STOP_BUFFER_SECONDS = int(os.getenv("RUN_STOP_BUFFER_SECONDS", "300"))
SITEMAP_SLICE_SIZE = int(os.getenv("SITEMAP_SLICE_SIZE", "0"))
PAGE_SLICE_SIZE = int(os.getenv("PAGE_SLICE_SIZE", "0"))
MAX_RUNS_PER_DAY = int(os.getenv("MAX_RUNS_PER_DAY", "3"))
TRACKED_LINK_CONTAINERS = "p a[href], li a[href], ol a[href]"
IGNORED_SCHEMES = {"mailto", "tel", "javascript", "data"}
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
IGNORED_ANCHOR_TEXTS = {"send", "share"}
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
REMOVE_FROM_CONTENT = [
    "header",
    "footer",
    "nav",
    "aside",
    "form",
    ".sidebar",
    ".menu",
    ".newsletter",
    ".share",
    ".social",
    ".related",
    ".comments",
    ".footer",
    ".header",
    ".breadcrumbs",
]
TRACKED_CONTENT_SELECTORS = [
    "article",
    "main article",
    "[role='main'] article",
    "[role='main']",
    "main",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".post-body",
    ".entry",
    ".content",
]
AGGRESSIVE_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap.xml.gz",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemapindex.xml",
    "/wp-sitemap.xml",
    "/sitemaps.xml",
    "/sitemap.php",
    "/sitemap/sitemap.xml",
    "/sitemap/index.xml",
    "/index.php/sitemap.xml",
    "/index.php/sitemap.xml.gz",
    "/index.php/sitemap_index.xml",
    "/post-sitemap.xml",
    "/page-sitemap.xml",
    "/article-sitemap.xml",
    "/news-sitemap.xml",
    "/product-sitemap.xml",
    "/category-sitemap.xml",
]


@dataclass
class SiteRecord:
    site_id: str
    site: str
    name: str
    registered_domain: str
    language: str
    source_record_id: str
    sitemap: str
    status: str
    priority: str
    cadence_days: int
    theme_raw: str
    theme_primary: str
    visits: str
    semrush_traffic: str
    majestic_trust_flow: str
    majestic_ref_domains: str
    moz_domain_authority: str
    notes: str


@dataclass
class OutgoingLink:
    target_domain: str
    target_url: str
    anchor_text: str
    rel_flags: list[str]
    is_follow: bool


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


def log_info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def log_warn(message: str) -> None:
    print(f"[WARN] {message}", flush=True)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def state_int(value: object, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: object) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl_gz(path: Path, rows: Iterable[dict[str, object]]) -> None:
    ensure_dir(path.parent)
    with gzip.open(path, "at", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        return ""
    parts = urlsplit(cleaned)
    if not parts.scheme or not parts.netloc:
        return ""
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def registered_domain(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    host = cleaned
    if "://" in cleaned:
        host = urlsplit(cleaned).netloc
    host = host.split("@")[-1].split(":")[0].strip(".").lower()
    if not host:
        return ""
    extracted = tldextract.extract(host)
    domain = getattr(extracted, "top_domain_under_public_suffix", "")
    if domain:
        return domain.lower()
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return host.lower()


def should_ignore_target_domain(target_domain: str) -> bool:
    normalized = (target_domain or "").strip().lower()
    if not normalized:
        return True
    if normalized in IGNORED_TARGET_DOMAINS:
        return True
    return normalized.split(".", 1)[0] in IGNORED_TARGET_DOMAIN_LABELS


def session_with_headers() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_response(session: requests.Session, url: str, timeout: int) -> requests.Response:
    response = session.get(
        url,
        timeout=(max(1, min(SITEMAP_CONNECT_TIMEOUT, timeout)), timeout),
        allow_redirects=True,
    )
    if response.status_code >= 400:
        response.raise_for_status()
    return response


def compute_remaining_timeout(timeout: int, deadline: float | None) -> int:
    if deadline is None:
        return timeout
    remaining = int(deadline - time.monotonic())
    if remaining <= 0:
        raise requests.Timeout("site budget exceeded")
    return max(1, min(timeout, remaining))


def get_with_retries(
    session: requests.Session,
    url: str,
    timeout: int,
    deadline: float | None = None,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            effective_timeout = compute_remaining_timeout(timeout, deadline)
            return fetch_response(session, url, effective_timeout)
        except requests.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in RETRYABLE_STATUS_CODES or attempt == HTTP_RETRIES:
                raise
        except requests.RequestException as exc:
            last_error = exc
            if attempt == HTTP_RETRIES:
                raise
        sleep_seconds = min(attempt, 3)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.Timeout("site budget exceeded")
            sleep_seconds = min(sleep_seconds, max(0, remaining))
        time.sleep(sleep_seconds)
    if last_error:
        raise last_error
    raise RuntimeError(f"Unexpected retry state for {url}")


def maybe_decompress(content: bytes, url: str) -> bytes:
    if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content)
        except OSError:
            return content
    return content


def local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def extract_from_robots(robots_text: str) -> list[str]:
    matches: list[str] = []
    for line in robots_text.splitlines():
        match = re.match(r"(?i)\s*sitemap\s*:\s*(\S+)", line.strip())
        if match:
            matches.append(match.group(1).strip())
    return matches


def extract_from_html(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    for tag in soup.find_all(["a", "link"]):
        href = tag.get("href")
        if not href:
            continue
        if "sitemap" not in href.lower():
            continue
        candidates.append(urljoin(base_url, href.strip()))
    return candidates


def base_variants(site_url: str) -> list[str]:
    normalized = normalize_url(site_url)
    if not normalized:
        return []
    parts = urlsplit(normalized)
    hosts = {parts.netloc}
    if parts.netloc.startswith("www."):
        hosts.add(parts.netloc[4:])
    else:
        hosts.add(f"www.{parts.netloc}")
    schemes = {parts.scheme, "https", "http"}
    base_path = parts.path.rstrip("/")
    paths = {base_path, ""}
    variants: list[str] = []
    seen: set[str] = set()
    for scheme in schemes:
        for host in hosts:
            for path in paths:
                value = urlunsplit((scheme, host, path, "", ""))
                if value not in seen:
                    seen.add(value)
                    variants.append(value)
    return variants


def looks_like_xml_sitemap(content: bytes, url: str) -> bool:
    payload = maybe_decompress(content, url)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return False
    return local_name(root.tag) in {"urlset", "sitemapindex"}


def fetch_soft(
    session: requests.Session,
    url: str,
    timeout: int,
    deadline: float | None = None,
) -> tuple[requests.Response | None, str]:
    try:
        effective_timeout = compute_remaining_timeout(timeout, deadline)
        response = session.get(
            url,
            timeout=(max(1, min(SITEMAP_CONNECT_TIMEOUT, effective_timeout)), effective_timeout),
            allow_redirects=True,
        )
        if response.status_code >= 400:
            response.close()
            return None, f"http_{response.status_code}"
        return response, "ok"
    except requests.Timeout:
        return None, "timeout"
    except requests.RequestException as exc:
        return None, exc.__class__.__name__.lower()


def site_state_dir(base_dir: Path) -> Path:
    return base_dir / "data" / "state" / "sites"


def snapshot_dir(base_dir: Path) -> Path:
    return base_dir / "data" / "state" / "snapshots"


def ever_seen_dir(base_dir: Path) -> Path:
    return base_dir / "data" / "state" / "ever_seen"


def rejections_dir(base_dir: Path) -> Path:
    return base_dir / "data" / "state" / "rejections"


def runtime_state_dir(base_dir: Path) -> Path:
    return base_dir / "data" / "state" / "runtime"


def site_state_path(base_dir: Path, site_id: str) -> Path:
    return site_state_dir(base_dir) / f"{site_id}.json"


def snapshot_path(base_dir: Path, site_id: str) -> Path:
    return snapshot_dir(base_dir) / f"{site_id}.json"


def ever_seen_path(base_dir: Path, site_id: str) -> Path:
    return ever_seen_dir(base_dir) / f"{site_id}.json"


def page_events_path(base_dir: Path, day: str) -> Path:
    return base_dir / "data" / "events" / "pages" / f"{day}.jsonl.gz"


def link_events_path(base_dir: Path, day: str) -> Path:
    return base_dir / "data" / "events" / "links" / f"{day}.jsonl.gz"


def rejection_events_path(base_dir: Path, day: str) -> Path:
    return rejections_dir(base_dir) / f"{day}.jsonl.gz"


def crawl_state_path(base_dir: Path) -> Path:
    return runtime_state_dir(base_dir) / "crawl_state.json"


def page_queue_path(base_dir: Path, run_token: str) -> Path:
    return runtime_state_dir(base_dir) / f"page_queue_{run_token}.jsonl"


def site_queue_path(base_dir: Path, run_token: str) -> Path:
    return runtime_state_dir(base_dir) / f"site_queue_{run_token}.json"


def load_url_set(path: Path) -> set[str]:
    payload = load_json(path, {})
    return set(payload.get("urls", []))


def current_day_iso() -> str:
    return date.today().isoformat()


def save_url_set(path: Path, urls: Iterable[str], sitemap_url: str) -> None:
    write_json(
        path,
        {
            "updated_on": date.today().isoformat(),
            "sitemap_url": sitemap_url,
            "urls": sorted(set(urls)),
        },
    )


def catalog_sites_path(base_dir: Path) -> Path:
    return base_dir / "catalog" / "sites.csv"


def load_sites(base_dir: Path) -> list[SiteRecord]:
    path = catalog_sites_path(base_dir)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if (reader.fieldnames or []) != SITE_HEADERS:
            raise RuntimeError("Invalid headers in catalog/sites.csv")
        rows: list[SiteRecord] = []
        for row in reader:
            rows.append(
                SiteRecord(
                    site_id=row["site_id"],
                    site=row["site"],
                    name=row["name"],
                    registered_domain=row["registered_domain"],
                    language=row["language"],
                    source_record_id=row["source_record_id"],
                    sitemap=row["sitemap"],
                    status=row["status"],
                    priority=row["priority"],
                    cadence_days=max(1, int((row["cadence_days"] or "7").strip() or "7")),
                    theme_raw=row["theme_raw"],
                    theme_primary=row["theme_primary"],
                    visits=row["visits"],
                    semrush_traffic=row["semrush_traffic"],
                    majestic_trust_flow=row["majestic_trust_flow"],
                    majestic_ref_domains=row["majestic_ref_domains"],
                    moz_domain_authority=row["moz_domain_authority"],
                    notes=row["notes"],
                )
            )
    return rows


def load_site_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def save_site_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SITE_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def load_config(base_dir: Path) -> dict[str, object]:
    path = base_dir / "config" / "pipeline.json"
    return load_json(
        path,
        {
            "default_cadence_days": 7,
            "default_priority": "normal",
            "crawler": {"max_workers": 12, "timeout_seconds": 25, "max_sites_per_run": 0},
        },
    )


def site_priority_rank(priority: str) -> int:
    return {"high": 0, "normal": 1, "low": 2}.get((priority or "").strip().lower(), 1)


def parse_sitemap(
    session: requests.Session,
    sitemap_url: str,
    visited: set[str] | None = None,
    timeout: int | None = None,
    deadline: float | None = None,
    documents_seen: list[int] | None = None,
) -> tuple[set[str], bool, str]:
    normalized_sitemap_url = normalize_url(sitemap_url)
    if not normalized_sitemap_url:
        return set(), False, "invalid_sitemap_url"
    if visited is None:
        visited = set()
    if documents_seen is None:
        documents_seen = [0]
    if deadline is not None and time.monotonic() >= deadline:
        return set(), False, "site_budget_exceeded"
    if normalized_sitemap_url in visited:
        return set(), True, "already_visited"
    if documents_seen[0] >= MAX_SITEMAP_DOCUMENTS:
        return set(), False, "max_sitemap_documents"
    visited.add(normalized_sitemap_url)
    documents_seen[0] += 1
    try:
        response = get_with_retries(
            session,
            normalized_sitemap_url,
            timeout or SITEMAP_TIMEOUT,
            deadline=deadline,
        )
        raw_bytes = response.content
        final_url = response.url
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        return set(), False, f"http_{status}"
    except requests.Timeout:
        return set(), False, "timeout"
    except requests.RequestException as exc:
        return set(), False, exc.__class__.__name__.lower()

    xml_bytes = maybe_decompress(raw_bytes, final_url)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return set(), False, "invalid_xml"

    root_name = local_name(root.tag)
    if root_name == "urlset":
        urls: set[str] = set()
        for url_node in root:
            if local_name(url_node.tag) != "url":
                continue
            for child in url_node:
                if local_name(child.tag) == "loc" and child.text:
                    normalized = normalize_url(child.text)
                    if normalized:
                        urls.add(normalized)
        return urls, True, "ok"

    if root_name == "sitemapindex":
        urls: set[str] = set()
        all_ok = True
        reason = "ok"
        for sitemap_node in root:
            if local_name(sitemap_node.tag) != "sitemap":
                continue
            child_url = ""
            for child in sitemap_node:
                if local_name(child.tag) == "loc" and child.text:
                    child_url = child.text.strip()
                    break
            if not child_url:
                continue
            child_urls, child_ok, child_reason = parse_sitemap(
                session,
                child_url,
                visited,
                timeout=timeout,
                deadline=deadline,
                documents_seen=documents_seen,
            )
            urls.update(child_urls)
            if not child_ok:
                all_ok = False
                reason = child_reason
        return urls, all_ok, reason

    return set(), False, "unsupported_xml_root"


def discover_sitemap(
    session: requests.Session,
    site: SiteRecord,
    timeout: int | None = None,
    deadline: float | None = None,
) -> tuple[str, str, list[str]]:
    effective_timeout = timeout or SITEMAP_TIMEOUT
    checked: list[str] = []
    if deadline is not None and time.monotonic() >= deadline:
        return "", "site_budget_exceeded", checked
    if site.sitemap:
        checked.append(site.sitemap)
        response, status = fetch_soft(session, site.sitemap, effective_timeout, deadline=deadline)
        if response is not None:
            final_url = response.url
            if looks_like_xml_sitemap(response.content, final_url):
                response.close()
                return final_url, "known_sitemap", checked
            response.close()
        return "", status, checked

    variants = base_variants(site.site)
    for base in variants:
        if deadline is not None and time.monotonic() >= deadline:
            return "", "site_budget_exceeded", checked
        robots_url = f"{base}/robots.txt"
        checked.append(robots_url)
        response, status = fetch_soft(session, robots_url, effective_timeout, deadline=deadline)
        if response is not None:
            try:
                candidates = extract_from_robots(response.text)
            finally:
                response.close()
            for candidate in candidates:
                if deadline is not None and time.monotonic() >= deadline:
                    return "", "site_budget_exceeded", checked
                checked.append(candidate)
                candidate_response, candidate_status = fetch_soft(
                    session,
                    candidate,
                    effective_timeout,
                    deadline=deadline,
                )
                if candidate_response is None:
                    status = candidate_status
                    continue
                final_url = candidate_response.url
                is_sitemap = looks_like_xml_sitemap(candidate_response.content, final_url)
                candidate_response.close()
                if is_sitemap:
                    return final_url, "robots.txt", checked

    for base in variants:
        if deadline is not None and time.monotonic() >= deadline:
            return "", "site_budget_exceeded", checked
        for path in AGGRESSIVE_SITEMAP_PATHS:
            if deadline is not None and time.monotonic() >= deadline:
                return "", "site_budget_exceeded", checked
            candidate = f"{base}{path}"
            checked.append(candidate)
            response, _status = fetch_soft(session, candidate, effective_timeout, deadline=deadline)
            if response is None:
                continue
            final_url = response.url
            is_sitemap = looks_like_xml_sitemap(response.content, final_url)
            response.close()
            if is_sitemap:
                return final_url, "common_path", checked

    for base in variants:
        if deadline is not None and time.monotonic() >= deadline:
            return "", "site_budget_exceeded", checked
        response, _status = fetch_soft(session, base, effective_timeout, deadline=deadline)
        if response is None:
            continue
        try:
            if "text/html" not in response.headers.get("content-type", ""):
                continue
            candidates = extract_from_html(response.text, response.url)
        finally:
            response.close()
        for candidate in candidates:
            if deadline is not None and time.monotonic() >= deadline:
                return "", "site_budget_exceeded", checked
            checked.append(candidate)
            candidate_response, _candidate_status = fetch_soft(
                session,
                candidate,
                effective_timeout,
                deadline=deadline,
            )
            if candidate_response is None:
                continue
            final_url = candidate_response.url
            is_sitemap = looks_like_xml_sitemap(candidate_response.content, final_url)
            candidate_response.close()
            if is_sitemap:
                return final_url, "homepage_link", checked

    return "", "no_sitemap_found", checked


def normalized_anchor_text(anchor) -> str:
    return re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()


def anchor_rel_flags(anchor) -> list[str]:
    values = anchor.get("rel", [])
    if isinstance(values, str):
        values = values.split()
    return sorted({value.strip().lower() for value in values if value.strip()})


def choose_fallback_content_node(soup: BeautifulSoup):
    candidates = []
    for selector in TRACKED_CONTENT_SELECTORS:
        for node in soup.select(selector):
            text_length = len(node.get_text(" ", strip=True))
            if text_length:
                candidates.append((text_length, node))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    return soup.body or soup


def extract_links_from_container(container, base_url: str, source_domain: str) -> list[OutgoingLink]:
    results: list[OutgoingLink] = []
    source_registered = registered_domain(source_domain)
    for anchor in container.select(TRACKED_LINK_CONTAINERS):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        anchor_text = normalized_anchor_text(anchor)
        if not anchor_text or anchor_text.lower() in IGNORED_ANCHOR_TEXTS:
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if not parts.scheme or not parts.netloc or parts.scheme.lower() in IGNORED_SCHEMES:
            continue
        normalized_target = normalize_url(absolute)
        if not normalized_target:
            continue
        target_domain = registered_domain(normalized_target)
        if not target_domain or target_domain == source_registered or should_ignore_target_domain(target_domain):
            continue
        rel_flags = anchor_rel_flags(anchor)
        results.append(
            OutgoingLink(
                target_domain=target_domain,
                target_url=normalized_target,
                anchor_text=anchor_text,
                rel_flags=rel_flags,
                is_follow="nofollow" not in rel_flags,
            )
        )
    return results


def extract_main_content_links(html: str, page_url: str, source_domain: str) -> list[OutgoingLink]:
    soup = BeautifulSoup(html, "html.parser")
    content_node = choose_fallback_content_node(soup)
    for selector in REMOVE_FROM_CONTENT:
        for node in content_node.select(selector):
            node.decompose()
    return extract_links_from_container(content_node, page_url, source_domain)


def fetch_page(url: str) -> tuple[str, str]:
    session = session_with_headers()
    response: requests.Response | None = None
    try:
        response = get_with_retries(session, url, PAGE_TIMEOUT)
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        title = ""
        if soup.title and soup.title.get_text():
            title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip()
        return html, title
    except requests.RequestException:
        return "", ""
    finally:
        if response is not None:
            response.close()
        session.close()


def write_latest_rejections_csv(base_dir: Path, rows: list[dict[str, object]]) -> None:
    path = rejections_dir(base_dir) / "latest.csv"
    ensure_dir(path.parent)
    headers = [
        "detected_on",
        "site_id",
        "site",
        "domain",
        "sitemap_url",
        "reason",
        "stage",
        "checked",
        "decision",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def load_recent_rejections(base_dir: Path) -> list[dict[str, object]]:
    path = rejections_dir(base_dir) / "latest.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def update_site_row(path: Path, site_id: str, updates: dict[str, str]) -> None:
    rows = load_site_rows(path)
    changed = False
    for row in rows:
        if row.get("site_id") != site_id:
            continue
        for key, value in updates.items():
            if row.get(key, "") != value:
                row[key] = value
                changed = True
        break
    if changed:
        save_site_rows(path, rows)


def crawler_decision_for_reason(reason: str) -> str:
    if reason in {"http_403", "http_404", "no_sitemap_found", "invalid_sitemap_url"}:
        return "exclude_candidate"
    return "retry_later"


def last_scan_day_for_site(base_dir: Path, site_id: str) -> str:
    state = load_json(site_state_path(base_dir, site_id), {})
    return str(state.get("last_scan_day", "") or "").strip()


def build_daily_site_queue(
    base_dir: Path,
    sites: list[SiteRecord],
    scan_day: str,
    limit: int,
) -> list[str]:
    ranked: list[tuple[str, int, str, str]] = []
    for site in sites:
        if site.status != "active":
            continue
        last_scan_day = last_scan_day_for_site(base_dir, site.site_id)
        if last_scan_day == scan_day:
            continue
        ranked.append(
            (
                last_scan_day or "0000-00-00",
                site_priority_rank(site.priority),
                site.registered_domain,
                site.site_id,
            )
        )
    ranked.sort()
    queue_ids = [site_id for _, _, _, site_id in ranked]
    return queue_ids[:limit] if limit > 0 else queue_ids


def load_site_queue(path: Path) -> list[str]:
    payload = load_json(path, {})
    site_ids = payload.get("site_ids", [])
    return [str(site_id).strip() for site_id in site_ids if str(site_id).strip()]


def save_site_queue(path: Path, site_ids: list[str], scan_day: str, site_limit: int) -> None:
    write_json(
        path,
        {
            "scan_day": scan_day,
            "site_limit": site_limit,
            "site_ids": site_ids,
        },
    )


def default_crawl_state(run_token: str, scan_day: str, total_sites: int, site_limit: int) -> dict[str, object]:
    return {
        "version": 1,
        "run_token": run_token,
        "scan_day": scan_day,
        "phase": "sitemaps",
        "site_cursor": 0,
        "page_cursor": 0,
        "total_sites": total_sites,
        "site_limit": site_limit,
        "seed_initial_urls": 1 if SEED_INITIAL_URLS else 0,
        "page_queue_count": 0,
        "sitemap_processed": 0,
        "pages_processed": 0,
        "rejections_written": 0,
        "runs_started_today": 0,
        "last_run_day": "",
        "can_dispatch_continuation": False,
        "needs_continuation": False,
        "done": False,
        "started_at": now_iso(),
        "updated_at": now_iso(),
    }


def save_crawl_state(base_dir: Path, state: dict[str, object]) -> None:
    state["updated_at"] = now_iso()
    write_json(crawl_state_path(base_dir), state)


def should_stop_before_next_slice(deadline: float, buffer_seconds: int = RUN_STOP_BUFFER_SECONDS) -> bool:
    return time.monotonic() >= max(0.0, deadline - max(0, buffer_seconds))


def load_page_queue(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            site_id = str(row.get("site_id", ""))
            url = str(row.get("url", ""))
            key = (site_id, url)
            if not site_id or not url or key in seen:
                continue
            seen.add(key)
            rows.append({"site_id": site_id, "url": url})
    return rows


def current_run_count(loaded_state: dict[str, object], current_day: str) -> int:
    if not loaded_state:
        return 1
    if str(loaded_state.get("last_run_day", "") or "") == current_day:
        return state_int(loaded_state.get("runs_started_today"), 0) + 1
    return 1


def scan_site(site: SiteRecord) -> tuple[SiteRecord, str, set[str], bool, str, list[str]]:
    session = session_with_headers()
    try:
        sitemap_url, discovery_stage, checked = discover_sitemap(session, site)
        if not sitemap_url:
            return site, "", set(), False, discovery_stage, checked
        current_urls, crawl_complete, reason = parse_sitemap(session, sitemap_url)
        return site, sitemap_url, current_urls, crawl_complete, reason, checked
    finally:
        session.close()


def process_sitemap_slice(
    base_dir: Path,
    run_token: str,
    event_day: str,
    slice_sites: list[SiteRecord],
    site_rows_path: Path,
    max_initial_urls_per_site: int,
    max_new_urls_per_site: int,
) -> tuple[int, int]:
    queue_rows: list[dict[str, object]] = []
    rejection_rows: list[dict[str, object]] = []
    latest_rejections = load_recent_rejections(base_dir)

    with ThreadPoolExecutor(max_workers=max(1, SITEMAP_WORKERS)) as executor:
        future_to_site = {executor.submit(scan_site, site): site for site in slice_sites}
        completed = 0
        for future in as_completed(future_to_site):
            site = future_to_site[future]
            try:
                site, sitemap_url, current_urls, crawl_complete, reason, checked = future.result()
            except Exception as exc:
                sitemap_url = site.sitemap
                current_urls = set()
                crawl_complete = False
                reason = exc.__class__.__name__.lower()
                checked = [site.site]

            state_path = site_state_path(base_dir, site.site_id)
            current_state = load_json(state_path, {})
            consecutive_failures = int(current_state.get("consecutive_failures", 0) or 0)

            if crawl_complete and sitemap_url and current_urls:
                if sitemap_url != site.sitemap:
                    update_site_row(site_rows_path, site.site_id, {"sitemap": sitemap_url})
                save_url_set(snapshot_path(base_dir, site.site_id), current_urls, sitemap_url)
                ever_seen_urls = load_url_set(ever_seen_path(base_dir, site.site_id))
                site_is_new = not current_state.get("last_success_at")
                if site_is_new:
                    candidate_urls = (
                        sorted(current_urls)[:max_initial_urls_per_site] if SEED_INITIAL_URLS else []
                    )
                else:
                    candidate_urls = sorted(url for url in current_urls - ever_seen_urls)
                if len(candidate_urls) > max_new_urls_per_site:
                    candidate_urls = candidate_urls[:max_new_urls_per_site]
                queue_rows.extend({"site_id": site.site_id, "url": url} for url in candidate_urls)

                updated_ever_seen = set(ever_seen_urls)
                updated_ever_seen.update(current_urls)
                save_url_set(ever_seen_path(base_dir, site.site_id), updated_ever_seen, sitemap_url)
                write_json(
                    state_path,
                    {
                        "site_id": site.site_id,
                        "domain": site.registered_domain,
                        "site": site.site,
                        "sitemap_url": sitemap_url,
                        "last_scan_at": now_iso(),
                        "last_scan_day": event_day,
                        "last_success_at": now_iso(),
                        "crawl_complete": True,
                        "urls_count": len(current_urls),
                        "reason": "ok",
                        "consecutive_failures": 0,
                    },
                )
            else:
                consecutive_failures += 1
                rejection = {
                    "detected_on": run_token,
                    "processed_on": event_day,
                    "site_id": site.site_id,
                    "site": site.site,
                    "domain": site.registered_domain,
                    "sitemap_url": sitemap_url or site.sitemap,
                    "reason": reason,
                    "stage": "discovery" if not sitemap_url else "crawl",
                    "checked": "; ".join(checked[:30]),
                    "decision": crawler_decision_for_reason(reason),
                }
                rejection_rows.append(rejection)
                latest_rejections.append(rejection)
                write_json(
                    state_path,
                    {
                        "site_id": site.site_id,
                        "domain": site.registered_domain,
                        "site": site.site,
                        "sitemap_url": sitemap_url or site.sitemap,
                        "last_scan_at": now_iso(),
                        "last_scan_day": event_day,
                        "last_success_at": current_state.get("last_success_at", ""),
                        "crawl_complete": False,
                        "urls_count": 0,
                        "reason": reason,
                        "consecutive_failures": consecutive_failures,
                    },
                )

            completed += 1
            if completed % PROGRESS_EVERY == 0 or completed == len(slice_sites):
                log_info(f"Sitemaps tranche: {completed}/{len(slice_sites)}")

    if queue_rows:
        append_jsonl(page_queue_path(base_dir, run_token), queue_rows)
    if rejection_rows:
        append_jsonl_gz(rejection_events_path(base_dir, event_day), rejection_rows)
        write_latest_rejections_csv(base_dir, latest_rejections)
    return len(queue_rows), len(rejection_rows)


def process_page_slice(
    event_day: str,
    queue_slice: list[dict[str, str]],
    site_by_id: dict[str, SiteRecord],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    title_results: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max(1, PAGE_WORKERS)) as executor:
        future_to_url = {executor.submit(fetch_page, row["url"]): row["url"] for row in queue_slice}
        completed = 0
        total = len(future_to_url)
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                title_results[url] = future.result()
            except Exception:
                title_results[url] = ("", "")
            completed += 1
            if completed % PROGRESS_EVERY == 0 or completed == total:
                log_info(f"Pages tranche: {completed}/{total}")

    page_events: list[dict[str, object]] = []
    link_events: list[dict[str, object]] = []
    for row in queue_slice:
        site = site_by_id.get(row["site_id"])
        if site is None:
            continue
        url = row["url"]
        html, title = title_results.get(url, ("", ""))
        if not html:
            continue
        outgoing_links = extract_main_content_links(html, url, site.registered_domain)
        page_events.append(
            {
                "detected_on": event_day,
                "processed_on": event_day,
                "site_id": site.site_id,
                "source_domain": site.registered_domain,
                "source_url": url,
                "title": title,
                "keyword": "",
                "raw_outgoing_links_count": len(outgoing_links),
                "unique_target_domains_count": len({link.target_domain for link in outgoing_links}),
            }
        )
        for link in outgoing_links:
            link_events.append(
                {
                    "detected_on": event_day,
                    "processed_on": event_day,
                    "site_id": site.site_id,
                    "source_domain": site.registered_domain,
                    "source_url": url,
                    "title": title,
                    "keyword": "",
                    "target_domain": link.target_domain,
                    "target_url": link.target_url,
                    "anchor_text": link.anchor_text,
                    "rel_flags": link.rel_flags,
                    "is_follow": link.is_follow,
                }
            )
    return page_events, link_events


def process() -> int:
    base_dir = repo_root()
    today = current_day_iso()
    config = load_config(base_dir)
    crawler_config = config.get("crawler", {})
    default_limit = int(crawler_config.get("max_sites_per_run", 0))
    if MAX_SITES_OVERRIDE_RAW is None or not MAX_SITES_OVERRIDE_RAW.strip():
        site_limit = default_limit
    else:
        site_limit = int(MAX_SITES_OVERRIDE_RAW.strip())
    max_initial_urls_per_site = int(crawler_config.get("max_initial_urls_per_site", MAX_INITIAL_URLS_PER_SITE))
    max_new_urls_per_site = int(crawler_config.get("max_new_urls_per_site", MAX_NEW_URLS_PER_SITE))

    sites = load_sites(base_dir)
    site_by_id_all = {site.site_id: site for site in sites}
    state = load_json(crawl_state_path(base_dir), {})
    run_count_today = current_run_count(state, today)
    can_dispatch_continuation = run_count_today < MAX_RUNS_PER_DAY
    deadline = time.monotonic() + max(60, RUN_BUDGET_SECONDS)
    sitemap_slice_size = SITEMAP_SLICE_SIZE or max(25, max(1, SITEMAP_WORKERS) * 8)
    page_slice_size = PAGE_SLICE_SIZE or max(25, max(1, PAGE_WORKERS) * 8)
    site_rows_path = catalog_sites_path(base_dir)
    while True:
        if not state or bool(state.get("done")):
            queue_ids = build_daily_site_queue(base_dir, sites, today, site_limit)
            if not queue_ids:
                log_info("Tous les sites actifs ont deja ete scannes aujourd'hui.")
                return 0
            run_token = today
            state = default_crawl_state(run_token, today, len(queue_ids), site_limit)
            save_site_queue(site_queue_path(base_dir, run_token), queue_ids, today, site_limit)
        else:
            run_token = str(state.get("run_token", today) or today)
            queue_ids = load_site_queue(site_queue_path(base_dir, run_token))
            if not queue_ids:
                raise RuntimeError(f"Missing site queue file for unfinished crawl state: {run_token}")

        state["runs_started_today"] = run_count_today
        state["last_run_day"] = today
        state["can_dispatch_continuation"] = can_dispatch_continuation
        state["needs_continuation"] = False
        save_crawl_state(base_dir, state)

        target_sites = [site_by_id_all[site_id] for site_id in queue_ids if site_id in site_by_id_all]
        expected_total = len(target_sites)
        queue_file = page_queue_path(base_dir, run_token)
        site_queue_file = site_queue_path(base_dir, run_token)
        site_by_id = {site.site_id: site for site in target_sites}

        log_info(
            f"Crawl cycle {run_token}: scan_day={state['scan_day']} phase={state['phase']} "
            f"sites={expected_total} limit={site_limit or 'all'} workers={SITEMAP_WORKERS}/{PAGE_WORKERS} "
            f"run={run_count_today}/{MAX_RUNS_PER_DAY}"
        )

        if state["phase"] == "sitemaps":
            while int(state["site_cursor"]) < expected_total:
                if should_stop_before_next_slice(deadline):
                    state["needs_continuation"] = True
                    state["can_dispatch_continuation"] = can_dispatch_continuation
                    save_crawl_state(base_dir, state)
                    log_warn("Budget runtime atteint pendant la phase sitemaps, arret propre.")
                    return 0
                start = int(state["site_cursor"])
                stop = min(expected_total, start + sitemap_slice_size)
                log_info(f"Sitemaps: traitement {start + 1}-{stop}/{expected_total}")
                queued_count, rejection_count = process_sitemap_slice(
                    base_dir,
                    run_token,
                    today,
                    target_sites[start:stop],
                    site_rows_path,
                    max_initial_urls_per_site,
                    max_new_urls_per_site,
                )
                state["site_cursor"] = stop
                state["sitemap_processed"] = stop
                state["page_queue_count"] = state_int(state.get("page_queue_count"), 0) + queued_count
                state["rejections_written"] = state_int(state.get("rejections_written"), 0) + rejection_count
                save_crawl_state(base_dir, state)

            state["phase"] = "pages"
            save_crawl_state(base_dir, state)

        queue_rows = load_page_queue(queue_file)
        state["page_queue_count"] = len(queue_rows)
        save_crawl_state(base_dir, state)
        if queue_rows:
            while int(state["page_cursor"]) < len(queue_rows):
                if should_stop_before_next_slice(deadline):
                    state["needs_continuation"] = True
                    state["can_dispatch_continuation"] = can_dispatch_continuation
                    save_crawl_state(base_dir, state)
                    log_warn("Budget runtime atteint pendant la phase pages, arret propre.")
                    return 0
                start = int(state["page_cursor"])
                stop = min(len(queue_rows), start + page_slice_size)
                log_info(f"Pages: traitement {start + 1}-{stop}/{len(queue_rows)}")
                page_events, link_events = process_page_slice(today, queue_rows[start:stop], site_by_id)
                if page_events:
                    append_jsonl_gz(page_events_path(base_dir, today), page_events)
                if link_events:
                    append_jsonl_gz(link_events_path(base_dir, today), link_events)
                state["page_cursor"] = stop
                state["pages_processed"] = stop
                save_crawl_state(base_dir, state)

        state["phase"] = "done"
        state["done"] = True
        state["needs_continuation"] = False
        state["can_dispatch_continuation"] = can_dispatch_continuation
        state["finished_at"] = now_iso()
        save_crawl_state(base_dir, state)
        try:
            queue_file.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            site_queue_file.unlink(missing_ok=True)
        except OSError:
            pass
        log_info(
            f"Crawl cycle {run_token} termine: sitemaps={state['sitemap_processed']}, "
            f"pages={state['pages_processed']}, queue={state['page_queue_count']}"
        )

        if str(state.get("scan_day", "")) != today and not should_stop_before_next_slice(deadline):
            log_info("Cycle en retard termine, reprise immediate du quota du jour.")
            state = {}
            continue
        if state["page_queue_count"] == 0:
            log_info("Aucune URL a enrichir pour ce cycle.")
        return 0


if __name__ == "__main__":
    raise SystemExit(process())
