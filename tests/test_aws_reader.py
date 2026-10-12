from urllib.parse import parse_qs, urlsplit

import boto3
from botocore.config import Config
from botocore.stub import ANY, Stubber
import pytest

from finbot_dashboard.aws_reader import AWSReader, FIELDS, object_location
from finbot_dashboard.config import Settings


def clients():
    session = boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing", region_name="us-east-1")
    return session.resource("dynamodb").meta.client, session.client("s3", config=Config(signature_version="s3v4"))


def params(kind, **extra):
    return {"TableName": f"finbot-prod-{kind}", "ProjectionExpression": ANY,
            "ExpressionAttributeNames": ANY, "ConsistentRead": True, "Limit": 100, **extra}


def test_paginated_scans_deserialize_records_and_skip_probe_rows():
    dynamodb, s3 = clients()
    with Stubber(dynamodb) as stub:
        # An empty page can still have a continuation key.
        stub.add_response("scan", {"Items": [], "LastEvaluatedKey": {"cik": {"S": "cursor"}}}, params("companies"))
        stub.add_response("scan", {"Items": [
            {"cik": {"S": "0000000001"}, "enabled": {"BOOL": True}, "repository_schema_version": {"N": "1"}},
            {"cik": {"S": "__deployment_check__fixture"}},
        ]}, params("companies", ExclusiveStartKey={"cik": "cursor"}))
        for kind in ("calendar", "filings", "artifacts"):
            stub.add_response("scan", {"Items": []}, params(kind))
        snapshot = AWSReader(Settings(), dynamodb, s3).load()
        assert snapshot.tables["companies"] == [{"cik": "0000000001", "enabled": True, "repository_schema_version": 1}]
        assert not snapshot.incomplete_tables
        assert snapshot.loaded_at.tzinfo is not None
        stub.assert_no_pending_responses()


def test_scan_budget_signals_incomplete_inventory():
    dynamodb, s3 = clients()
    with Stubber(dynamodb) as stub:
        for kind in FIELDS:
            key = "cik" if kind == "companies" else "expected_date" if kind == "calendar" else "accession_number" if kind == "filings" else "artifact_id"
            stub.add_response("scan", {"Items": [], "LastEvaluatedKey": {key: {"S": "cursor"}}}, params(kind))
        snapshot = AWSReader(Settings(max_scan_pages=1), dynamodb, s3).load()
        assert set(snapshot.incomplete_tables) == set(FIELDS)
        stub.assert_no_pending_responses()


def test_s3_links_are_get_only_and_preserve_encoded_object_keys():
    dynamodb, s3 = clients()
    with Stubber(s3):  # Signing should not contact AWS at all.
        urls = AWSReader(Settings(artifacts_bucket="test-artifacts"), dynamodb, s3).document_links(
            {"s3_uri": "s3://test-artifacts/filings/results%20%2525.htm"})
    opened, downloaded = map(urlsplit, urls)
    assert opened.netloc.startswith("test-artifacts.")
    assert opened.path == "/filings/results%20%2525.htm"
    assert parse_qs(opened.query)["X-Amz-Expires"] == ["900"]
    assert parse_qs(opened.query)["response-content-disposition"] == ["inline"]
    assert parse_qs(downloaded.query)["response-content-disposition"] == ["attachment; filename*=UTF-8''results%20%2525.htm"]


@pytest.mark.parametrize("uri", ["https://test-artifacts/key", "s3://test-artifacts", "s3://test-artifacts/key?x=1", "s3://user@test-artifacts/key"])
def test_bad_document_references_rejected(uri):
    with pytest.raises(ValueError):
        object_location(uri)


def test_optional_bucket_pin_rejects_other_bucket():
    dynamodb, s3 = clients()
    with pytest.raises(ValueError, match="bucket differs"):
        AWSReader(Settings(artifacts_bucket="expected-bucket"), dynamodb, s3).document_links({"s3_uri": "s3://other-bucket/key"})


def test_settings_resolve_profile_and_validate_read_limits():
    settings = Settings.from_env({"AWS_PROFILE": "local", "AWS_DEFAULT_REGION": "us-west-2", "FINBOT_DASHBOARD_TABLE_PREFIX": "finbot-test"})
    assert settings.profile == "local" and settings.region == "us-west-2"
    assert settings.table_name("calendar") == "finbot-test-calendar"
    with pytest.raises(ValueError):
        Settings.from_env({"FINBOT_DASHBOARD_MAX_SCAN_PAGES": "0"})
