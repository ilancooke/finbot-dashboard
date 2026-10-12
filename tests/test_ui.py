from datetime import datetime
from unittest.mock import Mock

from botocore.exceptions import ClientError
import pytest
from streamlit.testing.v1 import AppTest

from finbot_dashboard import ui
from conftest import NOW


@pytest.fixture
def app(snapshot, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(ui, "datetime", Clock)
    monkeypatch.setattr(ui, "load_snapshot", Mock(return_value=snapshot))
    monkeypatch.setattr(ui, "reader", Mock(return_value=Mock(document_links=Mock(return_value=("https://example.com/open", "https://example.com/download")))))
    return AppTest.from_file("app.py", default_timeout=10).run()


def test_operations_agenda_and_explorer_render(app):
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["1", "0", "1"]
    assert any("2026-10-12 09:00:00 MST" in caption.value for caption in app.caption)
    next(button for button in app.button if button.label == "See earnings agenda").click().run()
    assert not app.exception
    assert app.subheader[0].value == "Wednesday, October 14"
    next(button for button in app.button if button.label == "Browse all filings").click().run()
    assert not app.exception
    assert any("Calendar link" in text.value and "Unknown" in text.value for text in app.markdown)
    app.button("links:filing:0000000001-26-000001/results.htm").click().run()
    assert not app.exception
    ui.reader.return_value.document_links.assert_called_once()


def test_search_keeps_unplanned_activity_and_empty_views(app):
    app.text_input[0].set_value("results.htm").run()
    assert not app.exception
    assert app.metric[2].value == "1"
    app.text_input[0].set_value("DOES-NOT-EXIST").run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["0", "0", "0"]


def test_failed_refresh_retains_previous_data_with_warning(app):
    ui.load_snapshot.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "Scan")
    app.button[0].click().run()
    assert not app.exception
    assert any("last successful snapshot" in warning.value for warning in app.warning)
    assert app.metric[2].value == "1"
    ui.load_snapshot.clear.assert_called_once()


def test_initial_connection_failure_is_not_an_empty_inventory(monkeypatch):
    monkeypatch.setattr(ui, "load_snapshot", Mock(side_effect=ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "Scan")))
    app = AppTest.from_file("app.py").run()
    assert not app.exception
    assert "Unable to read AWS data" in app.error[0].value
    assert not app.metric


def test_partial_scan_is_prominently_disclosed(snapshot, app):
    snapshot.incomplete_tables = ("artifacts",)
    app.run()
    assert not app.exception
    assert any("Inventory is incomplete" in warning.value for warning in app.warning)
    assert app.metric[1].value == "1"
