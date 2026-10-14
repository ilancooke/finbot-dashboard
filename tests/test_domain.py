from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finbot_dashboard.domain import (
    arizona_time, artifact_status, build_inventory, calendar_health, count, event_key,
    recent_filings, sec_link, valid_match,
)
from conftest import NOW


def checkpoint(snapshot):
    parent = snapshot.tables["filings"][0]
    event = snapshot.tables["calendar"][0]
    event["expected_date"] = "2026-10-10"
    return {"repository_schema_version": 1, "expected_date": "__event_satisfaction__",
            "cik": event_key(event), "calendar_record_type": "satisfaction",
            "matched_accession_number": parent["accession_number"], "matched_form_type": "10-Q",
            "matched_filed_at": parent["filed_at"], "observed_expected_date": "2026-10-10",
            "satisfied_at": "2026-10-10T14:01:00Z", "window_start": "2026-10-09T04:00:00Z",
            "window_end": "2026-10-11T04:00:00Z", "grace_end": "2026-10-12T04:00:00Z",
            "match_reason": "original_10_q", "match_policy_version": "earnings-satisfaction-v1"}


@pytest.mark.parametrize("value, expected", [
    ("2026-07-15T06:00:00Z", "2026-07-14 23:00:00 MST"),
    ("2026-01-15T06:00:00Z", "2026-01-14 23:00:00 MST"),
    ("2026-10-12T10:00:00-04:00", "2026-10-12 07:00:00 MST"),
    ("2026-10-12T14:00:00", "Unknown"), (None, "Unknown"), ("bad", "Unknown"),
])
def test_arizona_year_round_and_rollover(value, expected):
    assert arizona_time(value) == expected


def test_all_activity_visible_without_speculative_match(snapshot):
    filings, events, warnings = build_inventory(snapshot)
    assert len(filings) == 1 and filings[0]["Calendar link"] == "Unknown"
    assert filings[0]["Download status"] == "Stored"
    assert filings[0]["Downloads"] == "1 of 1 file stored"
    assert filings[0]["Notifications"] == "1 of 1 published"
    assert not filings[0]["_attention"]
    assert events[0]["Expected date"] == "2026-10-14"
    assert events[0]["Status"] == "No confirmed filing"
    assert not warnings


def test_durable_match_and_rescheduled_identity(snapshot):
    event = snapshot.tables["calendar"][0]
    event["provider_event_id"] = "earnings-123"
    match = checkpoint(snapshot)
    event["expected_date"] = "2026-10-11"
    snapshot.tables["calendar"].append(match)
    snapshot.tables["artifacts"][0].pop("published_at")
    filings, events, _ = build_inventory(snapshot)
    assert filings[0]["Calendar link"] == "Matched"
    assert events[0]["Expected date"] == "2026-10-11"
    assert events[0]["Status"] == "Filing found"
    assert filings[0]["Notifications"] == "0 of 1 published"


@pytest.mark.parametrize("field,value", [
    ("matched_form_type", "10-Q/A"), ("matched_filed_at", "2026-10-11T14:00:00Z"),
    ("cik", '["yahoo","0000000002","date","2026-10-10"]'),
    ("match_policy_version", "future-policy"), ("repository_schema_version", 2),
    ("grace_end", "2026-10-10T14:00:00Z"), ("satisfied_at", "2026-10-10T13:00:00Z"),
])
def test_invalid_match_is_unknown_and_warns(snapshot, field, value):
    match = checkpoint(snapshot)
    match[field] = value
    snapshot.tables["calendar"].append(match)
    filings, events, warnings = build_inventory(snapshot)
    assert filings[0]["Calendar link"] == "Unknown"
    assert events[0]["Status"] == "No confirmed filing"
    assert warnings


def test_8k_requires_item_evidence(snapshot):
    match = checkpoint(snapshot)
    parent = snapshot.tables["filings"][0]
    parent["form_type"] = match["matched_form_type"] = "8-K"
    match["match_reason"] = "original_8_k_item_2_02"
    assert not valid_match(match, parent)
    match.update(matched_sec_items=["2.02"], sec_item_evidence_source="submissions")
    assert valid_match(match, parent)


def v2_checkpoint(snapshot, *, day="2026-10-13", accepted="2026-10-13T10:14:45Z"):
    match = checkpoint(snapshot)
    event, parent = snapshot.tables["calendar"][0], snapshot.tables["filings"][0]
    event["expected_date"] = day
    parent.update(form_type="8-K", filed_at=accepted)
    from finbot_dashboard.domain import MARKET
    expected = datetime.fromisoformat(day).date()
    start = datetime.combine(expected, datetime.min.time(), MARKET).astimezone(timezone.utc)
    end = datetime.combine(expected + timedelta(days=1), datetime.min.time(), MARKET).astimezone(timezone.utc)
    match.update(cik=event_key(event), observed_expected_date=day, matched_form_type="8-K",
                 matched_filed_at=accepted, satisfied_at=accepted, window_start=start.isoformat(),
                 window_end=end.isoformat(), grace_end=end.isoformat(), match_reason="original_8_k_item_2_02",
                 match_policy_version="earnings-satisfaction-v2", matched_sec_items=["2.02"],
                 sec_item_evidence_source="submissions.recent.items")
    return match


@pytest.mark.parametrize("accepted", ["2026-10-13T10:14:45Z", "2026-10-13T10:28:19Z", "2026-10-13T10:30:38Z"])
def test_v2_early_filing_links_agenda_to_completed_downloads(snapshot, accepted):
    snapshot.tables["calendar"].append(v2_checkpoint(snapshot, accepted=accepted))
    filings, events, warnings = build_inventory(snapshot)
    assert filings[0]["Calendar link"] == "Matched"
    assert events[0]["Status"] == "Filing found"
    assert events[0]["Downloads"] == "1 of 1 file stored"
    assert events[0]["Accession"] == filings[0]["Accession"]
    assert not warnings


@pytest.mark.parametrize("day,accepted", [
    ("2026-03-08", "2026-03-09T03:59:59Z"),
    ("2026-11-01", "2026-11-02T04:59:59Z"),
])
def test_v2_dashboard_accepts_daylight_saving_day_bounds(snapshot, day, accepted):
    match = v2_checkpoint(snapshot, day=day, accepted=accepted)
    assert valid_match(match, snapshot.tables["filings"][0])


@pytest.mark.parametrize("changes", [
    {"window_start": "2026-10-13T11:30:00Z"},
    {"window_end": "2026-10-14T05:00:00Z", "grace_end": "2026-10-14T05:00:00Z"},
    {"grace_end": "2026-10-14T05:00:00Z"},
    {"observed_expected_date": "2026-10-14"},
    {"observed_expected_date": "9999-12-31"},
    {"matched_sec_items": []}, {"sec_item_evidence_source": None},
    {"match_reason": "any_filing"},
])
def test_v2_dashboard_rejects_invalid_bounds_dates_and_evidence(snapshot, changes):
    match = v2_checkpoint(snapshot)
    match.update(changes)
    assert not valid_match(match, snapshot.tables["filings"][0])


@pytest.mark.parametrize("accepted", ["2026-10-13T03:59:59Z", "2026-10-14T04:00:00Z"])
def test_v2_dashboard_does_not_link_adjacent_market_dates(snapshot, accepted):
    match = v2_checkpoint(snapshot, accepted=accepted)
    assert not valid_match(match, snapshot.tables["filings"][0])


def test_historical_errors_do_not_override_completed_work(snapshot):
    parent = snapshot.tables["filings"][0]
    doc = snapshot.tables["artifacts"][0]
    parent.update(failure_stage="ENUMERATE", failure_error="old error")
    doc.update(failure_stage="ACQUIRE", failure_error="old storage error")
    assert artifact_status(doc) == ("Stored", "Published")
    filings, _, _ = build_inventory(snapshot)
    assert filings[0]["Download status"] == "Stored" and not filings[0]["_attention"]
    doc.pop("published_at")
    assert artifact_status(doc) == ("Stored", "Pending")
    doc.update(failure_stage="PUBLISH", failure_error="SNS unavailable")
    assert artifact_status(doc) == ("Stored", "Retrying")
    assert build_inventory(snapshot)[0][0]["_attention"]


@pytest.mark.parametrize("updates, expected", [
    ({"s3_uri": None, "stored_at": None, "published_at": None}, ("Pending", "Not ready")),
    ({"s3_uri": None, "stored_at": None, "published_at": None, "failure_stage": "ACQUIRE", "failure_error": "timeout"}, ("Retrying", "Not ready")),
    ({"published_at": None, "terminal_at": "2026-10-12T15:03:00Z", "terminal_stage": "PUBLISH"}, ("Stored", "Failed")),
    ({"stored_at": None}, ("Unknown", "Unknown")),
    ({"repository_schema_version": 2}, ("Unknown", "Unknown")),
])
def test_download_and_publication_states(snapshot, updates, expected):
    doc = snapshot.tables["artifacts"][0]
    doc.update(updates)
    assert artifact_status(doc) == expected


def test_count_mismatch_and_capped_scans_never_look_complete(snapshot):
    snapshot.tables["filings"][0]["enumerated_artifact_count"] = Decimal("2")
    row = build_inventory(snapshot)[0][0]
    assert row["Download status"] == "Unknown"
    assert 'Loaded 1 file record; original discovery recorded 2' in row['_status_explanation']
    snapshot.tables["filings"][0]["enumerated_artifact_count"] = Decimal("1")
    snapshot.incomplete_tables = ("artifacts",)
    assert build_inventory(snapshot)[0][0]["Download status"] == "Unknown"


@pytest.mark.parametrize('initial,total', [(1, 2), (1, 3), (2, 3)])
def test_later_recovery_additions_use_current_inventory(snapshot, initial, total):
    snapshot.tables['filings'][0]['enumerated_artifact_count'] = Decimal(initial)
    original = snapshot.tables['artifacts'][0]
    for index in range(1, total):
        child = deepcopy(original)
        child.update(filename=f'exhibit{index}.htm', artifact_id=original['accession_number'] + f'/exhibit{index}.htm')
        snapshot.tables['artifacts'].append(child)
    row = build_inventory(snapshot)[0][0]
    assert row['Downloads'] == f'{total} of {total} files stored'
    assert row['Download status'] == 'Stored'
    assert row['Notifications'] == f'{total} of {total} published'
    assert not row['_attention'] and not row['_status_explanation']
    assert snapshot.tables['filings'][0]['enumerated_artifact_count'] == initial


def test_recovery_pending_and_notification_retry_are_visible(snapshot):
    child = deepcopy(snapshot.tables['artifacts'][0])
    child.update(filename='recovered.htm', artifact_id=child['accession_number'] + '/recovered.htm',
                 s3_uri=None, stored_at=None, published_at=None)
    snapshot.tables['artifacts'].append(child)
    row = build_inventory(snapshot)[0][0]
    assert row['Downloads'] == '1 of 2 files stored'
    assert row['Download status'] == 'Pending'
    assert row['Notifications'] == '1 of 2 published'
    child.update(s3_uri='s3://test-artifacts/recovered.htm', stored_at='2026-10-12T15:03:00Z',
                 failure_stage='PUBLISH', failure_error='SNS unavailable')
    row = build_inventory(snapshot)[0][0]
    assert row['Download status'] == 'Stored' and row['_attention']
    assert row['Notifications'] == '1 of 2 published'


@pytest.mark.parametrize('incomplete', [('artifacts',), ('filings',)])
def test_recovered_files_do_not_hide_incomplete_scans(snapshot, incomplete):
    child = deepcopy(snapshot.tables['artifacts'][0])
    child.update(filename='recovered.htm', artifact_id=child['accession_number'] + '/recovered.htm')
    snapshot.tables['artifacts'].append(child)
    snapshot.incomplete_tables = incomplete
    row = build_inventory(snapshot)[0][0]
    assert row['Download status'] == row['Notifications'] == 'Unknown'
    assert row['Downloads'] == '2 files stored / total unknown'
    assert 'inventory read is incomplete' in row['_status_explanation']


def test_orphans_and_selection_uncertainty_remain_visible(snapshot):
    doc = snapshot.tables["artifacts"][0]
    doc.update(selection_decision="UNRESOLVED", s3_uri=None, stored_at=None, published_at=None)
    row = build_inventory(snapshot)[0][0]
    assert row["Download status"] == "Selection unresolved" and row["_attention"]
    snapshot.tables["filings"] = []
    row = build_inventory(snapshot)[0][0]
    assert row["Accession"] == doc["accession_number"]
    assert row["Download status"] == "Unknown"


def test_recent_uses_acquisition_activity_not_old_acceptance(snapshot):
    snapshot.tables["filings"][0]["filed_at"] = "2020-01-01T14:00:00Z"
    rows = build_inventory(snapshot)[0]
    assert len(recent_filings(rows, NOW, 7)) == 1
    assert not recent_filings(rows, datetime(2026, 11, 1, tzinfo=timezone.utc), 7)
    doc = snapshot.tables["artifacts"][0]
    doc["discovered_at"] = "2026-11-01T01:00:00Z"
    assert len(recent_filings(build_inventory(snapshot)[0], datetime(2026, 11, 1, tzinfo=timezone.utc), 7)) == 1


def test_calendar_tombstone_hidden_not_filings(snapshot):
    snapshot.tables["calendar"][0]["calendar_active"] = False
    filings, events, _ = build_inventory(snapshot)
    assert len(filings) == 1 and not events


def test_calendar_health_checks_scope_age_coverage_and_failures(snapshot):
    assert calendar_health(snapshot, NOW, 48)[0]["Status"] == "Current"
    sync = snapshot.tables["calendar"][1]
    sync.update(last_error="provider timeout", last_error_at="2026-10-12T15:00:00Z")
    assert calendar_health(snapshot, NOW, 48)[0]["Error"] == "provider timeout"
    sync["last_error_at"] = "2026-10-12T13:00:00Z"
    assert not calendar_health(snapshot, NOW, 48)[0]["Error"]
    snapshot.tables["companies"].append({"cik": "0000000002", "enabled": True})
    assert calendar_health(snapshot, NOW, 48)[0]["Status"] == "Stale / unknown"
    snapshot.tables["companies"].pop()
    assert calendar_health(snapshot, NOW.replace(day=15), 48)[0]["Status"] == "Stale / unknown"
    snapshot.incomplete_tables = ("calendar",)
    assert calendar_health(snapshot, NOW, 48)[0]["Status"] == "Stale / unknown"


def test_invalid_metadata_and_external_links():
    assert count(Decimal("NaN")) is None and count(True) is None
    assert count(Decimal("1.5")) is None and count(Decimal("12")) == 12
    assert sec_link("https://example.com/document") is None
    assert sec_link("https://[invalid") is None
    assert sec_link("https://www.sec.gov/Archives/document.htm")


def v3_checkpoint(snapshot):
    match = v2_checkpoint(snapshot)
    parent = snapshot.tables['filings'][0]
    parent.update(form_type='6-K', selection_policy='earnings-acquisition-v3',
                  selection_decision='SELECT', selection_reason='earnings_6_k')
    match.update(matched_form_type='6-K', match_reason='original_6_k_earnings',
                 match_policy_version='earnings-satisfaction-v3', matched_sec_items=[])
    match.pop('sec_item_evidence_source')
    return match


def test_6k_earnings_match_is_displayed_from_completed_selection(snapshot):
    snapshot.tables['calendar'].append(v3_checkpoint(snapshot))
    filings, events, warnings = build_inventory(snapshot)
    assert filings[0]['Calendar link'] == 'Matched' and events[0]['Status'] == 'Filing found'
    assert not warnings


@pytest.mark.parametrize('changes', [
    {'selection_decision': 'UNRESOLVED'}, {'selection_reason': 'primary_report'},
    {'selection_policy': 'earnings-acquisition-v2'}, {'enumeration_completed_at': None},
    {'terminal_at': '2026-10-13T15:00:00Z'}, {'form_type': '6-K/A'},
])
def test_6k_matches_require_their_qualified_parent(snapshot, changes):
    match = v3_checkpoint(snapshot)
    snapshot.tables['filings'][0].update(changes)
    assert not valid_match(match, snapshot.tables['filings'][0])


@pytest.mark.parametrize('changes', [
    {'match_policy_version': 'earnings-satisfaction-v2'}, {'matched_sec_items': ['2.02']},
    {'sec_item_evidence_source': 'submissions.recent.items'},
    {'grace_end': '2026-10-14T05:00:00Z'}, {'match_reason': 'original_10_q'},
])
def test_6k_does_not_borrow_item_evidence_or_legacy_matching(snapshot, changes):
    match = v3_checkpoint(snapshot)
    match.update(changes)
    assert not valid_match(match, snapshot.tables['filings'][0])
