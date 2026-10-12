"""Dashboard settings; credentials are resolved by the AWS SDK."""

from dataclasses import dataclass
import os

CACHE_SECONDS = 60


@dataclass(frozen=True)
class Settings:
    region: str = "us-east-1"
    profile: str | None = None
    table_prefix: str = "finbot-prod"
    max_scan_pages: int = 50
    calendar_stale_hours: int = 48
    artifacts_bucket: str | None = None

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        settings = cls(
            region=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1",
            profile=env.get("AWS_PROFILE") or None,
            table_prefix=env.get("FINBOT_DASHBOARD_TABLE_PREFIX", "finbot-prod"),
            max_scan_pages=int(env.get("FINBOT_DASHBOARD_MAX_SCAN_PAGES", "50")),
            calendar_stale_hours=int(env.get("FINBOT_DASHBOARD_CALENDAR_STALE_HOURS", "48")),
            artifacts_bucket=env.get("FINBOT_DASHBOARD_ARTIFACTS_BUCKET") or None,
        )
        if not settings.table_prefix.strip() or not settings.region.strip():
            raise ValueError("AWS region and table prefix must be nonempty")
        if not 1 <= settings.max_scan_pages <= 1000:
            raise ValueError("FINBOT_DASHBOARD_MAX_SCAN_PAGES must be between 1 and 1000")
        if not 1 <= settings.calendar_stale_hours <= 720:
            raise ValueError("FINBOT_DASHBOARD_CALENDAR_STALE_HOURS must be between 1 and 720")
        return settings

    def table_name(self, kind: str) -> str:
        return f"{self.table_prefix}-{kind}"
