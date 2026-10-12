"""Presentation facts derived from the ingestion service's durable records."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from finbot_dashboard.aws_reader import Snapshot

ARIZONA = ZoneInfo("America/Phoenix")
MARKET = ZoneInfo("America/New_York")
MATCH_POLICY = "earnings-satisfaction-v1"


def instant(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def arizona_time(value) -> str:
    parsed = instant(value)
    return parsed.astimezone(ARIZONA).strftime("%Y-%m-%d %H:%M:%S MST") if parsed else "Unknown"


def calendar_date(value) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def count(value) -> int | None:
    if isinstance(value, Decimal) and not value.is_finite():
        return None
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool) and value >= 0 and value == int(value):
        return int(value)
    return None


def active_error(record, stage) -> str | None:
    if record.get("terminal_stage") == stage:
        return record.get("terminal_error") or record.get("failure_error")
    if record.get("failure_stage") == stage:
        return record.get("failure_error")
    return None


def sec_link(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme == "https" and parsed.netloc in {"www.sec.gov", "sec.gov"} else None


def event_key(event) -> str:
    event_id = event.get("provider_event_id")
    return json.dumps([event.get("provider"), event.get("cik"),
                       "id" if event_id is not None else "date",
                       event_id if event_id is not None else event.get("expected_date")],
                      separators=(",", ":"))


def valid_match(item, filing) -> bool:
    """Trust only a compatible durable checkpoint with matching parent evidence."""
    try:
        identity = json.loads(item["cik"])
        filed = instant(filing.get("filed_at"))
        start, end, grace = (instant(item.get(key)) for key in ("window_start", "window_end", "grace_end"))
        satisfied = instant(item.get("satisfied_at"))
        reasons = {"10-Q": "original_10_q", "10-K": "original_10_k", "8-K": "original_8_k_item_2_02"}
        return bool(
            item.get("repository_schema_version") == filing.get("repository_schema_version") == 1
            and item.get("calendar_record_type") == "satisfaction"
            and item.get("match_policy_version") == MATCH_POLICY
            and len(identity) == 4 and all(isinstance(part, str) and part for part in identity)
            and item["cik"] == json.dumps(identity, separators=(",", ":"))
            and identity[2] in {"id", "date"}
            and identity[1] == filing.get("cik")
            and item.get("matched_accession_number") == filing.get("accession_number")
            and item.get("matched_form_type") == filing.get("form_type")
            and filing.get("form_type") in reasons
            and item.get("match_reason") == reasons.get(filing.get("form_type"))
            and calendar_date(item.get("observed_expected_date"))
            and (identity[2] != "date" or identity[3] == item.get("observed_expected_date"))
            and filed and filed == instant(item.get("matched_filed_at"))
            and start and end and grace and satisfied
            and start < end <= grace and start <= filed < grace and satisfied >= filed
            and (filing.get("form_type") != "8-K" or
                 ("2.02" in item.get("matched_sec_items", []) and item.get("sec_item_evidence_source")))
        )
    except (KeyError, TypeError, ValueError):
        return False


def artifact_status(artifact) -> tuple[str, str]:
    if artifact.get("repository_schema_version") != 1:
        return "Unknown", "Unknown"
    stored = instant(artifact.get("stored_at"))
    published = instant(artifact.get("published_at"))
    malformed = any(artifact.get(key) and not instant(artifact[key]) for key in ("stored_at", "published_at", "terminal_at"))
    if malformed or bool(artifact.get("s3_uri")) != bool(stored) or (published and not stored):
        return "Unknown", "Unknown"
    if artifact.get("selection_decision") == "EXCLUDE" and not stored:
        return "Not selected", "Not ready"
    if artifact.get("selection_decision") == "UNRESOLVED" and not stored:
        return "Selection unresolved", "Not ready"
    terminal = bool(artifact.get("terminal_at"))
    storage = "Stored" if stored else "Failed" if terminal else "Retrying" if active_error(artifact, "ACQUIRE") else "Pending"
    notification = ("Published" if published else "Failed" if terminal and stored else
                    "Retrying" if active_error(artifact, "PUBLISH") and stored else "Pending" if stored else "Not ready")
    return storage, notification


def calendar_health(snapshot: Snapshot, now: datetime, stale_hours: int) -> list[dict]:
    result = []
    enabled = {row.get("cik") for row in snapshot.tables["companies"] if row.get("enabled") is True}
    for row in snapshot.tables["calendar"]:
        if row.get("expected_date") != "__calendar_sync__":
            continue
        success = row.get("full_success", {})
        completed, observed = instant(success.get("completed_at")), instant(success.get("run", {}).get("observed_at"))
        run = success.get("run", {})
        start, end = calendar_date(run.get("start_date")), calendar_date(run.get("end_date"))
        today = now.astimezone(MARKET).date()
        scope = bool(start and end and start <= today <= end and
                     enabled == set(run.get("company_ciks", [])) and "companies" not in snapshot.incomplete_tables)
        current = bool(row.get("repository_schema_version") == 1 and observed and completed and
                       timedelta(0) <= now - observed < timedelta(hours=stale_hours) and scope and
                       "calendar" not in snapshot.incomplete_tables)
        failure = row.get("last_error") if instant(row.get("last_error_at")) and (
            not completed or instant(row["last_error_at"]) > completed) else None
        result.append({"Provider": row.get("cik", "Unknown"), "Status": "Current" if current else "Stale / unknown",
                       "Last full sync": arizona_time(completed), "Coverage": f"{start} to {end}" if start and end else "Unknown",
                       "Company scope": "Matches" if scope else "Unknown / changed", "Error": failure or ""})
    return result


def build_inventory(snapshot: Snapshot) -> tuple[list[dict], list[dict], list[str]]:
    parents = {row.get("accession_number"): row for row in snapshot.tables["filings"] if row.get("accession_number")}
    children = defaultdict(list)
    for artifact in snapshot.tables["artifacts"]:
        children[artifact.get("accession_number")].append(artifact)
    matches, warnings = defaultdict(list), []
    for checkpoint in snapshot.tables["calendar"]:
        if checkpoint.get("expected_date") == "__event_satisfaction__":
            parent = parents.get(checkpoint.get("matched_accession_number"), {})
            if valid_match(checkpoint, parent):
                matches[parent["accession_number"]].append(checkpoint)
            else:
                warnings.append("A calendar checkpoint could not be verified against its filing.")
    result = []
    for accession in parents.keys() | children.keys():
        documents = children[accession]
        parent = parents.get(accession, {})
        identity = parent or (documents[0] if documents else {})
        statuses = [artifact_status(doc) for doc in documents]
        stored = sum(storage == "Stored" for storage, _ in statuses)
        published = sum(notification == "Published" for _, notification in statuses)
        expected_count = count(parent.get("enumerated_artifact_count"))
        enumerated = bool(instant(parent.get("enumeration_completed_at")))
        complete = enumerated and expected_count is not None and expected_count == len(documents)
        unknown = (parent.get("repository_schema_version") != 1 or
                   "filings" in snapshot.incomplete_tables or "artifacts" in snapshot.incomplete_tables or
                   any(storage == "Unknown" for storage, _ in statuses) or (enumerated and not complete)
                   or any(parent.get(key) and not instant(parent[key]) for key in ("filed_at", "enumeration_completed_at", "terminal_at")))
        skipped = parent.get("selection_decision") == "EXCLUDE"
        failure = bool(parent.get("terminal_at")) or any("Failed" in pair for pair in statuses)
        retry = (not enumerated and bool(active_error(parent, "ENUMERATE"))) or any("Retrying" in pair for pair in statuses)
        if unknown:
            download_state = "Unknown"
        elif failure and (parent.get("terminal_stage") == "ENUMERATE" or any(storage == "Failed" for storage, _ in statuses)):
            download_state = "Failed"
        elif skipped:
            download_state = "Not selected"
        elif parent.get("selection_decision") == "UNRESOLVED" or any(storage == "Selection unresolved" for storage, _ in statuses):
            download_state = "Selection unresolved"
        elif complete and stored == len(documents):
            download_state = "Stored" if documents else "No selected documents"
        elif retry and not enumerated:
            download_state = "Enumeration retry"
        elif not enumerated:
            download_state = "Enumerating"
        else:
            download_state = "Retrying" if any(storage == "Retrying" for storage, _ in statuses) else "Pending"
        times = [instant(identity.get("discovered_at")), instant(parent.get("last_error_at")), instant(parent.get("failure_at"))]
        times += [instant(doc.get(key)) for doc in documents for key in ("discovered_at", "stored_at", "published_at", "last_error_at", "failure_at", "terminal_at")]
        latest = max((value for value in times if value), default=None)
        matched = matches.get(accession, [])
        row = {
            "Company": identity.get("ticker", "Unknown"), "Form": identity.get("form_type", "Unknown"),
            "Calendar link": "Matched" if matched else "Unknown",
            "Expected date": ", ".join(sorted({item["observed_expected_date"] for item in matched})),
            "Downloads": f"{stored}/{int(expected_count)} stored" if expected_count is not None else f"{stored} stored / total unknown",
            "Download status": download_state,
            "Notifications": "Unknown" if unknown else f"{published}/{int(expected_count)} published" if expected_count is not None else "Not ready",
            "Accepted": arizona_time(parent.get("filed_at")), "Discovered": arizona_time(identity.get("discovered_at")),
            "Last activity": arizona_time(latest), "Accession": accession,
            "_activity": latest, "_parent": parent, "_artifacts": documents, "_matches": matched,
            "_attention": bool(unknown or failure or retry or download_state == "Selection unresolved") and not skipped,
        }
        result.append(row)
    result.sort(key=lambda row: (row["_activity"] or datetime.min.replace(tzinfo=timezone.utc), row["Accession"] or ""), reverse=True)
    events = []
    by_identity = {checkpoint["cik"]: row for row in result for checkpoint in row["_matches"]}
    for event in snapshot.tables["calendar"]:
        expected = calendar_date(event.get("expected_date"))
        if not expected or event.get("calendar_active", True) is not True:
            continue
        matched = by_identity.get(event_key(event))
        events.append({"Company": event.get("ticker", "Unknown"), "Expected date": expected.isoformat(),
                       "Timing": {"before_market": "Before US market", "after_market": "After US market"}.get(event.get("time_of_day"), "Unknown"),
                       "Status": "Unknown schema" if event.get("repository_schema_version") != 1 else "Filing found" if matched else "No confirmed filing",
                       "Downloads": matched["Downloads"] if matched else "Not ready",
                       "Provider": event.get("provider", "Unknown"), "Calendar updated": arizona_time(event.get("synced_at")),
                       "Accession": matched["Accession"] if matched else "", "_date": expected})
    events.sort(key=lambda event: (event["_date"], event["Company"]))
    unsupported = sum(item.get("repository_schema_version") != 1 for items in snapshot.tables.values() for item in items)
    if unsupported:
        warnings.append(f"{unsupported} records have an unsupported schema; affected statuses may be unknown.")
    return result, events, sorted(set(warnings))


def recent_filings(rows, now, days):
    cutoff = now - timedelta(days=days) if days else None
    return [row for row in rows if not cutoff or not row["_activity"] or row["_activity"] >= cutoff]


def artifact_rows(filings):
    result = []
    for filing in filings:
        for artifact in filing["_artifacts"]:
            storage, notification = artifact_status(artifact)
            result.append({"Company": artifact.get("ticker", "Unknown"), "Form": artifact.get("form_type", "Unknown"),
                           "Document": artifact.get("filename", "Unknown"), "Type": artifact.get("document_type", "Unknown"),
                           "Calendar link": filing["Calendar link"], "Download status": storage,
                           "Notification": notification, "Stored": arizona_time(artifact.get("stored_at")),
                           "Artifact": artifact.get("artifact_id", "Unknown"), "_artifact": artifact})
    result.sort(key=lambda row: instant(row["_artifact"].get("stored_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return result
