from copy import deepcopy
from datetime import datetime, timezone

import pytest

from finbot_dashboard.aws_reader import Snapshot

NOW = datetime(2026, 10, 12, 16, tzinfo=timezone.utc)


@pytest.fixture
def snapshot():
    filing = {
        "repository_schema_version": 1, "cik": "0000000001", "ticker": "TEST",
        "accession_number": "0000000001-26-000001", "form_type": "10-Q",
        "filed_at": "2026-10-10T14:00:00Z", "discovered_at": "2026-10-12T15:00:00Z",
        "enumeration_completed_at": "2026-10-12T15:01:00Z", "enumerated_artifact_count": 1,
        "selection_decision": "SELECT", "filing_index_url": "https://www.sec.gov/Archives/test/index.htm",
    }
    artifact = {key: filing[key] for key in (
        "repository_schema_version", "cik", "ticker", "accession_number", "form_type", "discovered_at", "selection_decision")}
    artifact.update(artifact_id=filing["accession_number"] + "/results.htm", filename="results.htm",
                    document_type="10-Q", s3_uri="s3://test-artifacts/filings/results.htm",
                    stored_at="2026-10-12T15:02:00Z", published_at="2026-10-12T15:02:01Z",
                    sec_url="https://www.sec.gov/Archives/test/results.htm", size_bytes=1234)
    event = {"repository_schema_version": 1, "cik": filing["cik"], "ticker": "TEST",
             "expected_date": "2026-10-14", "provider": "yahoo", "time_of_day": "before_market",
             "synced_at": "2026-10-12T14:00:00Z"}
    sync = {"repository_schema_version": 1, "expected_date": "__calendar_sync__", "cik": "yahoo",
            "calendar_record_type": "sync", "full_success": {
                "completed_at": "2026-10-12T14:00:00Z", "run": {
                    "observed_at": "2026-10-12T13:59:00Z", "start_date": "2026-10-12",
                    "end_date": "2026-11-10", "company_ciks": [filing["cik"]]}}}
    return Snapshot(deepcopy({"companies": [{"repository_schema_version": 1, "cik": filing["cik"], "enabled": True}],
                              "calendar": [event, sync], "filings": [filing], "artifacts": [artifact]}), NOW)
