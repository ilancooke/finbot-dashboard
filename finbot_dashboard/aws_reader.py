"""Read-only AWS access. No ingestion code or write APIs are used."""

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlsplit

import boto3
from botocore.config import Config

from finbot_dashboard.config import Settings

COMMON = (
    "repository_schema_version", "cik", "ticker", "accession_number", "form_type",
    "discovered_at", "retry_count", "last_error", "last_error_at", "terminal_at",
    "terminal_stage", "terminal_error", "failure_stage", "failure_error", "failure_at",
    "acquisition_failures", "publication_failures", "enumeration_failures",
    "selection_decision", "selection_reason",
    "pending_work_kind",
)
FIELDS = {
    "companies": ("repository_schema_version", "cik", "ticker", "name", "enabled"),
    "calendar": (
        "repository_schema_version", "expected_date", "cik", "ticker", "provider",
        "time_of_day", "provider_event_id", "synced_at", "calendar_active",
        "calendar_record_type", "full_success", "near_term_success", "latest_run",
        "last_error", "last_error_at", "matched_accession_number", "matched_filed_at",
        "matched_form_type", "observed_expected_date", "satisfied_at", "window_start",
        "window_end", "grace_end", "match_reason", "match_policy_version",
        "matched_sec_items", "sec_item_evidence_source",
    ),
    "filings": COMMON + (
        "filed_at", "filing_index_url", "primary_document_name",
        "enumeration_completed_at", "enumerated_artifact_count",
    ),
    "artifacts": COMMON + (
        "artifact_id", "filename", "document_type", "sec_url", "s3_uri", "stored_at",
        "published_at", "content_type", "size_bytes",
    ),
}


@dataclass
class Snapshot:
    tables: dict[str, list[dict]]
    loaded_at: datetime
    incomplete_tables: tuple[str, ...] = ()


def object_location(uri: str) -> tuple[str, str]:
    parts = urlsplit(uri)
    if (parts.scheme != "s3" or not parts.netloc or parts.query or parts.fragment
            or parts.username or parts.port or not parts.path.lstrip("/")):
        raise ValueError("Invalid stored-document S3 reference")
    return parts.netloc, unquote(parts.path[1:])


class AWSReader:
    def __init__(self, settings: Settings, dynamodb, s3):
        self.settings = settings
        self.dynamodb = dynamodb
        self.s3 = s3

    @classmethod
    def connect(cls, settings: Settings):
        session = boto3.Session(profile_name=settings.profile, region_name=settings.region)
        options = Config(connect_timeout=5, read_timeout=10,
                         retries={"mode": "standard", "total_max_attempts": 3})
        dynamodb = session.resource("dynamodb", config=options).meta.client
        s3 = session.client("s3", config=options.merge(Config(signature_version="s3v4")))
        return cls(settings, dynamodb, s3)

    def load(self) -> Snapshot:
        tables, incomplete = {}, []
        for kind, fields in FIELDS.items():
            names = {f"#f{i}": name for i, name in enumerate(fields)}
            pages = self.dynamodb.get_paginator("scan").paginate(
                TableName=self.settings.table_name(kind),
                ProjectionExpression=", ".join(names),
                ExpressionAttributeNames=names,
                ConsistentRead=True,
                PaginationConfig={"PageSize": 100},
            )
            items = []
            for page_number, page in enumerate(pages, 1):
                items.extend(item for item in page.get("Items", []) if not self._fixture(item))
                if page_number >= self.settings.max_scan_pages:
                    if page.get("LastEvaluatedKey"):
                        incomplete.append(kind)
                    break
            tables[kind] = items
        return Snapshot(tables, datetime.now(timezone.utc), tuple(incomplete))

    @staticmethod
    def _fixture(item):
        return any(str(item.get(key, "")).startswith("__deployment_check__")
                   for key in ("cik", "accession_number", "artifact_id", "expected_date"))

    def document_links(self, artifact: dict) -> tuple[str, str]:
        """Sign GET links on demand; the browser retrieves bytes directly from S3."""
        bucket, key = object_location(artifact["s3_uri"])
        if self.settings.artifacts_bucket and bucket != self.settings.artifacts_bucket:
            raise ValueError("Document bucket differs from the configured artifacts bucket")
        filename = quote(key.rsplit("/", 1)[-1], safe="")
        params = {"Bucket": bucket, "Key": key}
        opened = self.s3.generate_presigned_url(
            "get_object", Params={**params, "ResponseContentDisposition": "inline"},
            ExpiresIn=900, HttpMethod="GET",
        )
        downloaded = self.s3.generate_presigned_url(
            "get_object", Params={**params,
                "ResponseContentDisposition": f"attachment; filename*=UTF-8''{filename}"},
            ExpiresIn=900, HttpMethod="GET",
        )
        return opened, downloaded
