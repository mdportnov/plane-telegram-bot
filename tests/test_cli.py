import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import main
from bot.service.api import PlaneAPIError

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "af0d57f1-107e-4554-91a1-7c15022c16e1"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "BOT_TOKEN",
        "API_TOKEN",
        "WORKSPACE_SLUG",
        "BASE_URL",
        "PLANE_APP_URL",
        "PLANE_WORK_ITEMS_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_missing_config_explains_how_to_start(capsys):
    assert main.main([]) == 1
    assert "config.example.yaml" in capsys.readouterr().err


def test_telegram_setup_needs_only_bot_token(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    with patch.object(main, "PlaneNotifierBot") as bot:
        assert main.main(["--telegram-setup"]) == 0
    bot.assert_called_once_with("test-token")
    bot.return_value.run.assert_called_once()


def test_list_projects_needs_no_config_or_telegram(monkeypatch, capsys):
    monkeypatch.setenv("API_TOKEN", "secret")
    monkeypatch.setenv("WORKSPACE_SLUG", "acme")
    with patch.object(main.PlaneAPI, "get_all_projects", return_value=[{"id": PROJECT, "name": "Demo"}]):
        assert main.main(["--list-projects"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == PROJECT


def test_dotenv_loaded_from_current_directory(tmp_path, capsys):
    (tmp_path / ".env").write_text("API_TOKEN=secret\nWORKSPACE_SLUG=acme\n")
    with patch.object(main.PlaneAPI, "get_members", return_value=[]):
        assert main.main(["--list-members"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_states_require_project_id(capsys):
    assert main.main(["--list-states"]) == 1
    assert "--project-id" in capsys.readouterr().err


def test_api_failure_returns_nonzero_without_token(monkeypatch, capsys):
    monkeypatch.setenv("API_TOKEN", "do-not-print-this")
    monkeypatch.setenv("WORKSPACE_SLUG", "acme")
    with patch.object(main.PlaneAPI, "get_all_projects", side_effect=PlaneAPIError("HTTP 401")):
        assert main.main(["--list-projects"]) == 1
    output = capsys.readouterr()
    assert "HTTP 401" in output.err
    assert "do-not-print-this" not in output.err


def test_readme_setup_check_with_mock_plane(tmp_path, monkeypatch, capsys):
    for source, target in (
        ("config.example.yaml", "config.yaml"),
        ("projects.example.json", "projects.json"),
        ("members.example.json", "members.json"),
    ):
        (tmp_path / target).write_text((ROOT / source).read_text())
    monkeypatch.setenv("API_TOKEN", "secret")
    monkeypatch.setenv("WORKSPACE_SLUG", "acme")
    api = Mock()
    api.get_project.return_value = {"name": "Demo"}
    api.map_states_by_ids.return_value = {"1": "Todo", "2": "In Progress", "3": "In Review"}
    with patch.object(main, "make_api", return_value=api), patch.object(main, "PlaneNotifierBot") as bot:
        assert main.main(["--check-config"]) == 0
    assert "checks passed" in capsys.readouterr().out
    bot.assert_not_called()
    api.create_issue.assert_not_called()
    api.get_project_tasks.assert_called_once_with(PROJECT)


def test_legacy_member_check_reports_unsupported_endpoint(capsys):
    api = Mock(work_items_endpoint="issues")
    api.get_project.return_value = {"name": "Demo"}
    api.map_states_by_ids.return_value = {"todo": "Todo"}
    api.get_members.side_effect = PlaneAPIError("not found", 404)
    main.check_config(api, {"report_states_list": ["Todo"]}, {PROJECT: "-123"}, {PROJECT: "Alice"})
    assert "could not be verified" in capsys.readouterr().out


@pytest.mark.parametrize("status,endpoint", [(403, "issues"), (404, "work-items")])
def test_member_check_does_not_hide_auth_or_current_api_errors(status, endpoint):
    api = Mock(work_items_endpoint=endpoint)
    api.get_project.return_value = {"name": "Demo"}
    api.map_states_by_ids.return_value = {"todo": "Todo"}
    api.get_members.side_effect = PlaneAPIError("failed", status)
    with pytest.raises(PlaneAPIError):
        main.check_config(api, {"report_states_list": ["Todo"]}, {PROJECT: "-123"}, {PROJECT: "Alice"})
