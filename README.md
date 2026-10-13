# finbot-dashboard

A read-only Streamlit dashboard for expected earnings and filing acquisition in AWS.
It reads the data maintained by `finbot-filings`; it does not run acquisition or
change operational state. The previous local catalog and stock application remains
in Git history.

## Views

- **Operations:** upcoming earnings, filings needing attention, recent filings and
  artifacts, and calendar freshness and coverage.
- **Earnings agenda:** expectations grouped by provider calendar date, alongside
  recent acquisition activity. Retained past expectations are also browsable.
- **Filing explorer:** search and filter filings, inspect document checkpoints, and
  open or download stored original documents through temporary S3 GET links.

All timestamp instants display in **Arizona time (`America/Phoenix`, MST,
UTC−07:00 year-round)**. Date-only earnings expectations retain the provider's
market-calendar date; they are not shifted to another day. Before/after-market
labels refer to the US market session.

All discovered filings and artifact records are included, including unplanned
documents. Calendar context does not restrict the acquisition inventory. A verified
ingestion satisfaction checkpoint produces **Matched**; its absence produces
**Unknown**, since it cannot prove that a document was unplanned. These records
remain visible in the **Unplanned / unknown** filter.

A qualifying filing can satisfy an expectation before its documents finish
downloading. Download/storage status and notification publication are shown
separately. Publication means SNS acknowledged the message; it does not confirm
downstream receipt or extracted financial results. The dashboard does not extract
EPS or other financial results.

Download and notification totals include all currently recorded files, including
attachments added by targeted recovery. The ingestion service's original discovery
count is a historical snapshot; it is not a fixed total. The filing detail explains
when later records increase that count. Fewer loaded records than the original
count, incomplete scans, and unsupported or inconsistent checkpoints still show
**Unknown**, with an explanation in the detail view.

## Run locally

From this repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
AWS_PROFILE=default .venv/bin/streamlit run app.py --server.address=127.0.0.1
```

Open <http://localhost:8501>. An existing authenticated AWS profile must have read
access to the source tables and artifacts. Credentials stay in the Python process;
the browser receives only displayed metadata and document links created on demand.
No local shared data directory, catalog refresh, dashboard hosting, or CDK deployment
is needed.

## Data and configuration

| Source | Use |
| --- | --- |
| DynamoDB Companies | Enabled company scope and identity |
| DynamoDB Calendar | Expectations, sync health, durable satisfaction checkpoints |
| DynamoDB Filings | Discovery, acceptance, selection and enumeration checkpoints |
| DynamoDB Artifacts | Documents, storage/publication checkpoints and stage failures |
| S3 | Original bytes through signed GET links, created only when requested |

The reader uses the [filings data contracts](https://github.com/ilancooke/finbot-filings/blob/main/docs/ARCHITECTURE.md)
without importing ingestion code. Schema version 1 is supported. Unsupported records,
missing parents, and inconsistent completion checkpoints are disclosed as unknown.
Deployment probe records and inactive calendar tombstones are excluded from their
respective views. Historical errors do not override a completed stage.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `AWS_PROFILE` | SDK credential chain | Local AWS profile; omit when using an IAM role |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | `us-east-1` | Source region; `AWS_REGION` takes precedence |
| `FINBOT_DASHBOARD_TABLE_PREFIX` | `finbot-prod` | Reads `<prefix>-companies`, `-calendar`, `-filings`, `-artifacts` |
| `FINBOT_DASHBOARD_MAX_SCAN_PAGES` | `50` | Maximum pages per table per refresh (1–1000) |
| `FINBOT_DASHBOARD_CALENDAR_STALE_HOURS` | `48` | Maximum age of a full calendar observation (1–720 hours) |
| `FINBOT_DASHBOARD_ARTIFACTS_BUCKET` | From each artifact's S3 URI | Optional bucket restriction for signed links |

Minimum AWS permissions are `dynamodb:Scan` on the four tables and `s3:GetObject`
on the artifact objects. Encrypted objects may also require `kms:Decrypt` on their
customer-managed key. An existing operator profile can run the app; a dedicated
dashboard identity should be limited to these reads. No write APIs are used.

Metadata is cached for 60 seconds. **Refresh** clears that cache. The page shows the
last successful read time; it refreshes on interaction rather than polling in the
background. If AWS access fails, the current browser session retains its previous
snapshot with a warning. Document links expire after 15 minutes (or sooner if their
signing credentials expire); create fresh links when needed.

The current source schema has no global recency index, so this first version uses
paginated metadata scans, with up to 100 evaluated records per request. The page
budget bounds read work. Scan projections reduce transferred metadata, not DynamoDB
read charges. Scans have no chronological ordering and are not an atomic snapshot
across tables. If a table hits the budget, the UI warns that counts and recent
activity are incomplete and avoids declaring filing downloads complete.

Time and search filters apply after loading. Recent activity is based on discovery,
storage, publication and error checkpoints, so newly acquired older filings are
visible. At larger inventory sizes, add a deliberate read model or index before
raising scan limits indefinitely.

## Docker

```bash
docker build -t finbot-dashboard .
docker run --rm -p 127.0.0.1:8501:8501 \
  -e AWS_PROFILE=default -e AWS_REGION=us-east-1 \
  -v "$HOME/.aws:/root/.aws:ro" \
  finbot-dashboard
```

Authenticate the host profile first. If it uses SSO, renew its session on the host
when needed. Forward any dashboard environment overrides with `-e`. Credentials
are mounted read-only and are never baked into the image. The image contains only
the application, dependencies and Streamlit settings.

## Development

```bash
.venv/bin/python -m compileall app.py finbot_dashboard
.venv/bin/python -m pytest
```

Tests use deterministic records, stubbed AWS clients and Streamlit's application
test runner. They do not contact AWS or mutate the shared data root. Hosting,
authentication for a shared deployment, and financial-result extraction are later
decisions.
