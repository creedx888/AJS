"""Small, polite client for Amazon's public careers search pages.

Amazon can change this undocumented endpoint at any time. Keep the response
normalizer permissive and report upstream errors instead of returning fake data.
"""
from __future__ import annotations

import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.amazon.jobs"
PAGE_SIZE = 100
MAX_WINDOW = 10_000
LOCATION_DISCOVERY_WINDOW = 1_000
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LocalAmazonJobsResearch/1.0)",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}


def _list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return [str(x).strip() for x in value if str(x).strip()]


def _first(obj, *keys, default=""):
    for key in keys:
        value = obj.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _clean(value):
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    if isinstance(value, dict):
        return str(_first(value, "display", "name", "label", default=""))
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _locations(raw):
    if isinstance(raw, dict):
        raw = [raw]
    result = []
    for entry in raw or []:
        if isinstance(entry, str):
            result.append({"city": "", "state": "", "countryCode": "", "country": "", "display": entry})
            continue
        if not isinstance(entry, dict):
            continue
        city = _clean(_first(entry, "city", "city_name"))
        state = _clean(_first(entry, "state", "region", "state_name"))
        code = _clean(_first(entry, "country_code", "countryCode", "country_code3"))
        country = _clean(_first(entry, "country", "country_name"))
        display = _clean(_first(entry, "display", "normalized_location", "location")) or ", ".join(x for x in (city, state, country or code) if x)
        result.append({"city": city, "state": state, "countryCode": code, "country": country, "display": display})
    return result


def normalize(job):
    if not isinstance(job, dict):
        return None
    job_id = str(_first(job, "job_id", "jobId", "id", "req_id", "requisition_id"))
    if not job_id:
        return None
    slug = _clean(_first(job, "slug", "job_slug"))
    path = _clean(_first(job, "job_path", "jobPath", "detail_url", "detailUrl"))
    if not path:
        path = f"/en/jobs/{job_id}/{slug}".rstrip("/")
    detail = path if path.startswith("http") else BASE + (path if path.startswith("/") else "/" + path)
    locations = _locations(_first(job, "locations", "location_list", default=[]))
    loc = _clean(_first(job, "location", "location_name", "normalized_location"))
    if not loc and locations:
        loc = locations[0]["display"]
    primary = locations[0] if locations else {}
    description = _clean(_first(job, "description", "job_description", "description_html", "jobDescription"))
    if "<" in description:
        description = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)
    posted = _clean(_first(job, "posted_date", "postedDate", "posting_date", "date_posted"))
    apply_url = _clean(_first(job, "url", "apply_url", "applyUrl", "application_url"))
    if not apply_url:
        apply_url = f"https://account.amazon.jobs/en-US/jobs/{job_id}/apply"
    return {
        "title": _clean(_first(job, "title", "job_title", "name")),
        "jobId": job_id,
        "url": apply_url,
        "detailUrl": detail,
        "location": loc,
        "normalizedLocation": (
            _clean(_first(job, "normalized_location", "normalizedLocation"))
            or (primary.get("display", "") if primary else "")
            or loc
        ),
        "locations": locations,
        "city": _clean(_first(job, "city")) or primary.get("city", ""),
        "state": _clean(_first(job, "state", "region")) or primary.get("state", ""),
        "countryCode": _clean(_first(job, "country_code", "countryCode")) or primary.get("countryCode", ""),
        "jobCategory": _clean(_first(job, "category", "job_category", "jobCategory")),
        "jobFamily": _clean(_first(job, "job_family", "jobFamily")),
        "team": _clean(_first(job, "team", "team_name")),
        "businessCategory": _clean(_first(job, "business_category", "businessCategory")),
        "jobScheduleType": _clean(_first(job, "job_type", "job_schedule_type", "jobScheduleType", "schedule_type")),
        "companyName": _clean(_first(job, "company_name", "companyName", default="Amazon")),
        "basicQualifications": _clean(_first(job, "basic_qualifications", "basicQualifications")),
        "preferredQualifications": _clean(_first(job, "preferred_qualifications", "preferredQualifications")),
        "description": description,
        "descriptionShort": _clean(_first(job, "description_short", "descriptionShort", "short_description", "description"))[:500],
        "postedDate": posted,
        "updatedAt": _clean(_first(job, "updated_at", "updatedAt", "updated_date")),
    }


def _search_json_url(search_url, offset, limit):
    parsed = urlparse(search_url)
    path = parsed.path
    if path.endswith(".json"):
        json_path = path
    else:
        json_path = path.rstrip("/") + ".json"
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in ("offset", "limit", "result_limit")]
    query.extend((("offset", str(offset)), ("result_limit", str(limit))))
    return urlunparse((parsed.scheme or "https", parsed.netloc or "www.amazon.jobs", json_path, "", urlencode(query), ""))


def _make_url(params, offset, limit, *, base_query=None, normalized_locations=None):
    if base_query is None:
        base_query = params.get("searchKeyword", "software engineer")
    query = {"base_query": base_query, "sort": "recent" if params.get("sortBy") == "recent" else "relevant", "offset": str(offset), "result_limit": str(limit)}
    pairs = list(query.items())
    pairs.extend(("normalized_location[]", value) for value in (normalized_locations or []))
    pairs.extend(("category[]", category) for category in _list(params.get("categories")))
    pairs.extend(("normalized_country_code[]", country) for country in _list(params.get("countries")))
    pairs.extend(("job_type[]", kind) for kind in _list(params.get("jobTypes")))
    return BASE + "/en/search.json?" + urlencode(pairs)


def _location_values(job):
    """Read location labels from Amazon records across its response variants."""
    value = _first(job, "normalized_location", "normalizedLocation", "locations", "location_list", default=[])
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        value = [value]
    results = []
    for item in value or []:
        if isinstance(item, str) and item.strip():
            results.append(item.strip())
        elif isinstance(item, dict):
            display = _clean(_first(item, "display", "normalized_location", "location", "name"))
            if display:
                results.append(display)
    for key in ("location", "location_name"):
        raw = _clean(job.get(key))
        if raw:
            results.append(raw)
    return results


def _job_matches_city(job, city):
    """Match the exact city across structured and display location fields."""
    wanted = city.strip().casefold()
    direct = _clean(_first(job, "city", "city_name"))
    if direct and direct.casefold() == wanted:
        return True
    for entry in _first(job, "locations", "location_list", default=[]) or []:
        if isinstance(entry, dict):
            city_value = _clean(_first(entry, "city", "city_name"))
            if city_value and city_value.casefold() == wanted:
                return True
    for label in _location_values(job):
        # Normalized labels start with the city; raw Amazon labels commonly
        # end with it (for example, "US, WA, Seattle").
        parts = [part.strip().casefold() for part in label.split(",") if part.strip()]
        if parts and (parts[0] == wanted or parts[-1] == wanted):
            return True
    return False


class SearchCancelled(Exception):
    """Raised when the user cancels an in-progress search."""


def _check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise SearchCancelled()


def _resolve_city(client, city, delay, cancel_event=None):
    """Resolve a city to the exact label required by normalized_location[]."""
    found = set()
    offset = 0
    while offset < LOCATION_DISCOVERY_WINDOW:
        _check_cancelled(cancel_event)
        response = client.get(_make_url({"searchKeyword": "", "sortBy": "relevant"}, offset, PAGE_SIZE, base_query=city.strip()))
        response.raise_for_status()
        _check_cancelled(cancel_event)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Amazon returned HTML while resolving the city filter.") from exc
        batch, total = _extract(payload)
        if not batch:
            break
        for job in batch:
            if not _job_matches_city(job, city):
                continue
            normalized = _first(job, "normalized_location", "normalizedLocation", default=[])
            if isinstance(normalized, str):
                normalized = [normalized]
            elif isinstance(normalized, dict):
                normalized = [normalized]
            for item in normalized or []:
                label = _clean(_first(item, "display", "normalized_location", "location", "name")) if isinstance(item, dict) else _clean(item)
                if label:
                    found.add(label)
            if not normalized:
                for item in _first(job, "locations", "location_list", default=[]) or []:
                    if isinstance(item, dict):
                        label = _clean(_first(item, "display", "normalized_location", "location", "name"))
                        if label:
                            found.add(label)
        offset += len(batch)
        if offset >= total or len(batch) < PAGE_SIZE:
            break
        time.sleep(delay)
    # Some responses expose only a city/raw location instead of Amazon's
    # normalized label. In that case, skip the upstream location parameter;
    # scrape() still applies the exact city match to returned jobs.
    return sorted(found)


def _extract(payload):
    if isinstance(payload, list):
        return payload, len(payload)
    if not isinstance(payload, dict):
        return [], 0
    jobs = _first(payload, "jobs", "results", "search_results", "searchResults", default=[])
    if isinstance(jobs, dict):
        jobs = _first(jobs, "jobs", "results", default=[])
    total = _first(payload, "hits", "total_hits", "totalHits", "total", "count", default=len(jobs) if isinstance(jobs, list) else 0)
    if isinstance(total, dict):
        total = total.get("value", 0)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = len(jobs) if isinstance(jobs, list) else 0
    return jobs if isinstance(jobs, list) else [], total


def scrape(params, cancel_event=None):
    max_results = int(params.get("maxResults", 100) or 0)
    ceiling = min(max_results if max_results > 0 else MAX_WINDOW, MAX_WINDOW)
    sources = [None, *_list(params.get("searchUrls"))]
    output, seen, total_hits = [], set(), 0
    delay = max(0.2, float(os.getenv("REQUEST_DELAY", "1.0")))
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        normalized_locations = _resolve_city(client, params["location"], delay, cancel_event) if params.get("location", "").strip() else []
        request_ceiling = MAX_WINDOW if params.get("location", "").strip() and not normalized_locations else ceiling
        for source in sources:
            offset = 0
            while offset < request_ceiling:
                _check_cancelled(cancel_event)
                url = _search_json_url(source, offset, PAGE_SIZE) if source else _make_url(params, offset, PAGE_SIZE, normalized_locations=normalized_locations)
                response = client.get(url)
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError:
                    raise RuntimeError("Amazon returned HTML instead of search JSON. The search endpoint may have changed or blocked this request.")
                batch, total = _extract(payload)
                total_hits += total if offset == 0 else 0
                if not batch:
                    break
                for raw in batch:
                    _check_cancelled(cancel_event)
                    job = normalize(raw)
                    if job and params.get("location", "").strip() and not _job_matches_city(raw, params["location"]):
                        continue
                    if job and job["jobId"] not in seen:
                        output.append(job)
                        seen.add(job["jobId"])
                        if max_results and len(output) >= max_results:
                            return output, total_hits
                offset += len(batch)
                if offset >= total or len(batch) < PAGE_SIZE:
                    break
                time.sleep(delay)
    return output[:max_results] if max_results else output[:MAX_WINDOW], total_hits

