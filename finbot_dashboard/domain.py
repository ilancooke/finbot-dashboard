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
MATCH_POLICIES = {"earnings-satisfaction-v1", "earnings-satisfaction-v2", "earnings-satisfaction-v3"}
DAY_MATCH_POLICIES = {"earnings-satisfaction-v2", "earnings-satisfaction-v3"}


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
        expected = calendar_date(item.get("observed_expected_date"))
        day_bounds = None
        if item.get("match_policy_version") in DAY_MATCH_POLICIES and expected:
            day_start = datetime.combine(expected, datetime.min.time(), MARKET).astimezone(timezone.utc)
            day_end = datetime.combine(expected + timedelta(days=1), datetime.min.time(), MARKET).astimezone(timezone.utc)
            day_bounds = (day_start, day_end, day_end)
        reasons = {"10-Q": "original_10_q", "10-K": "original_10_k", "8-K": "original_8_k_item_2_02",
                   "6-K": "original_6_k_earnings"}
        return bool(
            item.get("repository_schema_version") == filing.get("repository_schema_version") == 1
            and item.get("calendar_record_type") == "satisfaction"
            and item.get("match_policy_version") in MATCH_POLICIES
            and len(identity) == 4 and all(isinstance(part, str) and part for part in identity)
            and item["cik"] == json.dumps(identity, separators=(",", ":"))
            and identity[2] in {"id", "date"}
            and identity[1] == filing.get("cik")
            and item.get("matched_accession_number") == filing.get("accession_number")
            and item.get("matched_form_type") == filing.get("form_type")
            and filing.get("form_type") in reasons
            and item.get("match_reason") == reasons.get(filing.get("form_type"))
            and expected
            and (identity[2] != "date" or identity[3] == item.get("observed_expected_date"))
            and filed and filed == instant(item.get("matched_filed_at"))
            and start and end and grace and satisfied
            and start < end <= grace and start <= filed < grace and satisfied >= filed
            and (item.get("match_policy_version") not in DAY_MATCH_POLICIES or
                 (start, end, grace) == day_bounds)
            and ((filing.get("form_type") == "6-K") == (item.get("match_policy_version") == "earnings-satisfaction-v3"))
            and (filing.get("form_type") != "6-K" or
                 (filing.get("selection_policy") == "earnings-acquisition-v3"
                  and filing.get("selection_decision") == "SELECT"
                  and filing.get("selection_reason") == "earnings_6_k"
                  and instant(filing.get("enumeration_completed_at"))
                  and not filing.get("terminal_at")
                  and not item.get("matched_sec_items") and item.get("sec_item_evidence_source") is None))
            and (filing.get("form_type") != "8-K" or
                 ("2.02" in item.get("matched_sec_items", []) and item.get("sec_item_evidence_source")))
        )
    except (KeyError, TypeError, ValueError, OverflowError):
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
        # This is the first completed discovery snapshot, not a permanent total.
        # Explicit recovery can add children without rewriting that checkpoint.
        initial_count = count(parent.get("enumerated_artifact_count"))
        current_count = max(initial_count, len(documents)) if initial_count is not None else None
        enumerated = bool(instant(parent.get("enumeration_completed_at")))
        complete = enumerated and initial_count is not None and initial_count > 0 and initial_count <= len(documents)
        unknown_reasons = []
        if parent.get("repository_schema_version") != 1:
            unknown_reasons.append("The filing record is missing or has an unsupported schema.")
        partial_inventory = "filings" in snapshot.incomplete_tables or "artifacts" in snapshot.incomplete_tables
        if partial_inventory:
            unknown_reasons.append("The inventory read is incomplete; some files may be missing from this view.")
        if any(storage == "Unknown" for storage, _ in statuses):
            unknown_reasons.append("A file has incomplete or unsupported storage or notification data.")
        if enumerated and not complete:
            unknown_reasons.append("The original discovery count is missing or invalid." if not initial_count else
                                   f"Loaded {len(documents)} {'file record' if len(documents) == 1 else 'file records'}; original discovery recorded {initial_count}.")
        if any(parent.get(key) and not instant(parent[key]) for key in ("filed_at", "enumeration_completed_at", "terminal_at")):
            unknown_reasons.append("A filing timestamp is invalid.")
        unknown = bool(unknown_reasons)
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
            "Downloads": (f"{stored} of {current_count} {'file' if current_count == 1 else 'files'} stored" if current_count is not None and not partial_inventory
                          else f"{stored} files stored / total unknown"),
            "Download status": download_state,
            "Notifications": "Unknown" if unknown else f"{published} of {current_count} published" if current_count is not None else "Not ready",
            "Accepted": arizona_time(parent.get("filed_at")), "Discovered": arizona_time(identity.get("discovered_at")),
            "Last activity": arizona_time(latest), "Accession": accession,
            "_activity": latest, "_parent": parent, "_artifacts": documents, "_matches": matched,
            "_status_explanation": " ".join(unknown_reasons),
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
