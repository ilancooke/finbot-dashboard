"""Streamlit views for live acquisition metadata."""

from datetime import datetime, timedelta, timezone

from botocore.exceptions import BotoCoreError, ClientError
import streamlit as st

from finbot_dashboard.aws_reader import AWSReader
from finbot_dashboard.config import CACHE_SECONDS, Settings
from finbot_dashboard.domain import (
    MARKET, active_error, arizona_time, artifact_rows, artifact_status,
    build_inventory, calendar_health, count, recent_filings, sec_link,
)


@st.cache_resource(show_spinner=False)
def reader(settings: Settings) -> AWSReader:
    return AWSReader.connect(settings)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def load_snapshot(settings: Settings):
    return reader(settings).load()


def navigate(page: str):
    st.session_state["page"] = page


def public_rows(rows, columns):
    return [{column: row.get(column, "") for column in columns} for row in rows]


def table(rows, columns, *, key=None, selectable=False):
    return st.dataframe(public_rows(rows, columns), hide_index=True, width="stretch",
                        on_select="rerun" if selectable else "ignore",
                        selection_mode="single-row", key=key,
                        column_config={"Accession": st.column_config.TextColumn(width="large"),
                                       "Document": st.column_config.TextColumn(width="large")})


FILING_COLUMNS = ["Company", "Form", "Calendar link", "Downloads", "Download status", "Last activity", "Accession"]
EVENT_COLUMNS = ["Company", "Expected date", "Timing", "Status", "Downloads", "Provider"]
ARTIFACT_COLUMNS = ["Company", "Document", "Type", "Calendar link", "Download status", "Notification", "Stored"]


def main():
    st.set_page_config(page_title="Finbot Dashboard", page_icon="FB", layout="wide")
    st.markdown("""<style>
      .stMainBlockContainer { max-width: 1400px; padding-top: 2rem; }
      [data-testid="stMetricValue"] { font-size: 2rem; }
    </style>""", unsafe_allow_html=True)
    try:
        settings = Settings.from_env()
    except ValueError as error:
        st.error(f"Invalid dashboard configuration: {error}")
        st.stop()
    header, refresh = st.columns([5, 1], vertical_alignment="center")
    with header:
        st.title("Finbot / Filings")
        st.caption(f"{settings.table_prefix} · {settings.region} · Read only · Arizona time (MST, UTC−07:00)")
    with refresh:
        if st.button("Refresh", width="stretch"):
            load_snapshot.clear()
    now = datetime.now(timezone.utc)
    stale_snapshot = False
    try:
        with st.spinner("Reading filings metadata…"):
            snapshot = load_snapshot(settings)
        st.session_state["last_snapshot"] = (settings, snapshot)
    except (BotoCoreError, ClientError, ValueError) as error:
        previous = st.session_state.get("last_snapshot")
        if not previous or previous[0] != settings:
            st.error("Unable to read AWS data. Check your AWS profile, region and read permissions, then refresh.")
            with st.expander("Connection details"):
                st.code(str(error))
            st.stop()
        snapshot = previous[1]
        stale_snapshot = True
        st.warning("AWS refresh failed. Showing the last successful snapshot; statuses may have changed.")
        with st.expander("Connection details"):
            st.code(str(error))
    st.caption(f"Last successful read: {arizona_time(snapshot.loaded_at)} · Metadata cache: {CACHE_SECONDS} seconds")
    health = calendar_health(snapshot, now, settings.calendar_stale_hours)
    if not health or any(row["Status"] != "Current" or row["Error"] for row in health):
        st.warning("Calendar freshness or coverage needs attention. Expected dates may be out of date; acquisition activity is still shown.")
    else:
        st.caption(f"Calendar current · Full sync: {health[0]['Last full sync']}")
    if snapshot.incomplete_tables:
        st.warning("Inventory is incomplete: the read limit was reached for " + ", ".join(snapshot.incomplete_tables)
                   + ". Counts reflect loaded records and may omit newer activity.")
    filings, events, warnings = build_inventory(snapshot)
    for message in warnings:
        st.warning(message)
    with st.expander("Calendar health and coverage"):
        if health:
            st.dataframe(health, hide_index=True, width="stretch")
        else:
            st.info("No calendar synchronization metadata is available.")
    with st.sidebar:
        st.header("View filters")
        search = st.text_input("Company, accession or filename", placeholder="Search all activity").strip().lower()
        period = st.selectbox("Recent activity", ["Last 7 days", "Last 30 days", "Last 90 days", "All history"])
        horizon = st.selectbox("Upcoming earnings", [7, 30], format_func=lambda value: f"Next {value} days")
        st.caption("Expected dates and market timing come from the provider calendar. All timestamps use Arizona time.")
    days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All history": 0}[period]
    recent = recent_filings(filings, now, days)
    if search:
        recent = [row for row in recent if search in " ".join([
            row["Company"], row["Accession"] or "", row["Form"],
            *[doc.get("filename", "") for doc in row["_artifacts"]]]).lower()]
        events = [event for event in events if search in f"{event['Company']} {event['Accession']}".lower()]
    market_today = now.astimezone(MARKET).date()
    upcoming = [event for event in events if market_today <= event["_date"] < market_today + timedelta(days=horizon)]
    page = st.segmented_control("View", ["Operations", "Earnings agenda", "Filing explorer"],
                                default="Operations", key="page", label_visibility="collapsed")
    if page == "Earnings agenda":
        agenda(upcoming, events, recent)
    elif page == "Filing explorer":
        explorer(recent, settings)
    else:
        operations(upcoming, recent, settings, horizon)
    if stale_snapshot:
        st.caption("Read-only view of previously loaded records; refresh to retry AWS access.")


def operations(upcoming, filings, settings, horizon):
    st.header("Operations")
    counters = st.columns(3)
    for column, label, value in zip(counters, [f"Expected in next {horizon} days", "Filings needing attention", "Without confirmed calendar match"],
                                    [len(upcoming), sum(row["_attention"] for row in filings), sum(row["Calendar link"] == "Unknown" for row in filings)]):
        with column, st.container(border=True):
            st.metric(label, value)
    attention = [row for row in filings if row["_attention"]]
    if attention:
        st.subheader("Needs attention")
        table(attention, FILING_COLUMNS)
    st.subheader("Upcoming expected earnings")
    if upcoming:
        table(upcoming, EVENT_COLUMNS)
    else:
        st.info("No expected earnings in this window and filter. Check calendar health for coverage.")
    st.button("See earnings agenda", on_click=navigate, args=("Earnings agenda",))
    st.subheader("Recent filings · All activity")
    if filings:
        table(filings, FILING_COLUMNS)
    else:
        st.info("No filing activity in this window and filter.")
    st.button("Explore filings", on_click=navigate, args=("Filing explorer",))
    st.caption("Unplanned documents are included. Unknown means no verified calendar link; it does not prove that a filing was unplanned.")
    recent_artifacts(filings, settings)


def agenda(upcoming, events, filings):
    st.header("Earnings agenda")
    schedule, activity = st.columns([1.5, 1])
    with schedule:
        if not upcoming:
            st.info("No upcoming expected earnings in this window and filter.")
        for day in sorted({event["_date"] for event in upcoming}):
            st.subheader(day.strftime("%A, %B %d"))
            table([event for event in upcoming if event["_date"] == day], ["Company", "Timing", "Status", "Downloads"])
        with st.expander("All retained calendar expectations"):
            if events:
                table(events, EVENT_COLUMNS + ["Calendar updated", "Accession"])
            else:
                st.info("No active calendar expectations are available.")
    with activity:
        st.subheader("Recent acquisition activity")
        for row in filings[:10]:
            with st.container(border=True):
                st.write(f"**{row['Company']} · {row['Form']}**")
                st.caption(row["Last activity"])
                st.write(f"Calendar: {row['Calendar link']} · {row['Downloads']}")
        if not filings:
            st.info("No recent filings in this window and filter.")
        st.button("Browse all filings", on_click=navigate, args=("Filing explorer",))


def explorer(filings, settings):
    st.header("Filing explorer")
    calendar, progress = st.columns(2)
    with calendar:
        link_filter = st.selectbox("Calendar link", ["All", "Matched", "Unplanned / unknown"])
    with progress:
        download_filter = st.selectbox("Download progress", ["All", "Needs attention", "Stored", "Pending / retrying"])
    visible = [row for row in filings if (link_filter == "All" or row["Calendar link"] == ("Unknown" if link_filter == "Unplanned / unknown" else link_filter))
               and (download_filter == "All" or (download_filter == "Needs attention" and row["_attention"])
                    or (download_filter == "Stored" and row["Download status"] == "Stored")
                    or (download_filter == "Pending / retrying" and row["Download status"] in {"Pending", "Retrying", "Enumerating", "Enumeration retry"}))]
    st.caption("All discovered filings remain browsable, including unplanned documents. A missing checkpoint is shown as Unknown.")
    if not visible:
        st.info("No filings match these filters.")
    else:
        listing, detail = st.columns([1.6, 1])
        with listing:
            selection = table(visible, ["Company", "Form", "Calendar link", "Downloads", "Download status"], key="filing_table", selectable=True)
        index = selection.selection.rows[0] if selection.selection.rows else 0
        selected = visible[index] if index < len(visible) else visible[0]
        with detail, st.container(border=True):
            filing_detail(selected, settings)
    recent_artifacts(filings, settings)


def filing_detail(filing, settings):
    st.subheader(f"{filing['Company']} · {filing['Form']}")
    st.caption(filing["Accession"])
    st.write(f"**Calendar link:** {filing['Calendar link']}")
    if filing["_matches"]:
        st.write(f"**Expected date:** {filing['Expected date']}")
        st.caption("Verified against the ingestion service's recorded match.")
    else:
        st.caption("No verified event-match checkpoint. This may be unplanned activity or an expectation that has not been linked.")
    st.write(f"**Downloads:** {filing['Downloads']} · {filing['Download status']}")
    st.write(f"**Notifications:** {filing['Notifications']}")
    st.caption("Publication is an SNS acknowledgment, not confirmation of downstream receipt.")
    st.write(f"**Accepted:** {filing['Accepted']}")
    st.write(f"**Discovered:** {filing['Discovered']}")
    source = sec_link(filing["_parent"].get("filing_index_url"))
    if source:
        st.link_button("SEC filing index", source)
    parent = filing["_parent"]
    if active_error(parent, "ENUMERATE") and not parent.get("enumeration_completed_at"):
        st.warning(active_error(parent, "ENUMERATE"))
        st.caption(f"Error recorded: {arizona_time(parent.get('failure_at'))}")
    for artifact in filing["_artifacts"]:
        with st.expander(artifact.get("filename", "Unnamed document")):
            document_detail(artifact, settings, "filing")


def recent_artifacts(filings, settings):
    rows = artifact_rows(filings)
    with st.expander("Recent artifacts · Expected and unplanned", expanded=True):
        if not rows:
            st.info("No artifact records in this window and filter.")
            return
        choice = table(rows, ARTIFACT_COLUMNS, key="artifact_table", selectable=True)
        if choice.selection.rows:
            index = choice.selection.rows[0]
            if index < len(rows):
                document_detail(rows[index]["_artifact"], settings, "recent")
        else:
            st.caption("Select an artifact to inspect its status and open or download the document.")


def document_detail(artifact, settings, context):
    st.write(artifact.get("filename", "Unnamed document"))
    stored, published = artifact_status(artifact)
    st.write(f"**Download:** {stored} · **Notification:** {published}")
    st.caption(f"Discovered: {arizona_time(artifact.get('discovered_at'))}")
    st.caption(f"Stored: {arizona_time(artifact.get('stored_at'))} · Published: {arizona_time(artifact.get('published_at'))}")
    size = count(artifact.get("size_bytes"))
    if size is not None:
        st.caption(f"Size: {size:,} bytes · {artifact.get('document_type', 'Unknown type')}")
    error = active_error(artifact, "ACQUIRE" if stored != "Stored" else "PUBLISH")
    if error and published != "Published":
        st.warning(error)
        st.caption(f"Error recorded: {arizona_time(artifact.get('failure_at'))}")
    source = sec_link(artifact.get("sec_url"))
    if source:
        st.link_button("SEC original", source)
    if stored == "Stored" and st.button("Create stored-document links", key=f"links:{context}:{artifact['artifact_id']}"):
        try:
            opened, downloaded = reader(settings).document_links(artifact)
        except (BotoCoreError, ClientError, ValueError) as error:
            st.error(f"Unable to create document links: {error}")
        else:
            st.link_button("Open stored document", opened)
            st.link_button("Download original bytes", downloaded)
            st.caption("Links expire in 15 minutes; create new links when needed.")
