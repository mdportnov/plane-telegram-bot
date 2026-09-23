import json
from pathlib import Path

import pytest

from bot.utils.utils import load_config_from_file, load_members_from_file, load_projects_from_file

PROJECT = "af0d57f1-107e-4554-91a1-7c15022c16e1"


def write_json(tmp_path, data):
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(data))
    return path


def test_mapping_normalization(tmp_path):
    path = write_json(tmp_path, [{"member_id": PROJECT, "telegram_id": "@Alice"}])
    assert load_members_from_file(path) == {PROJECT: "Alice"}
    path = write_json(tmp_path, [{"project_id": PROJECT, "chat_id": -100123}])
    assert load_projects_from_file(path) == {PROJECT: "-100123"}


@pytest.mark.parametrize(
    "data",
    [
        [{"member_id": PROJECT, "telegram_id": "@Alice"}],
        [{"project_id": "TEAM", "chat_id": "-123"}],
        [{"project_id": PROJECT, "chat_id": "@chat"}],
        [{"project_id": PROJECT, "chat_id": "-123"}] * 2,
        {},
        [{}],
    ],
)
def test_invalid_project_mappings(tmp_path, data):
    with pytest.raises(ValueError):
        load_projects_from_file(write_json(tmp_path, data))


def test_duplicate_member_username_case_insensitive(tmp_path):
    path = write_json(
        tmp_path,
        [
            {"member_id": PROJECT, "telegram_id": "Alice"},
            {"member_id": "55c56d6c-13f6-4dd1-be67-a39992eff736", "telegram_id": "@ALICE"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_members_from_file(path)


def test_config_defaults_and_relative_paths(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("projects_file_path: projects.json\n")
    config = load_config_from_file(path)
    assert config["cron_timezone"] == "UTC"
    assert config["projects_file_path"] == str(tmp_path / "projects.json")
    assert load_members_from_file(config["members_file_path"]) == {}


@pytest.mark.parametrize(
    "content",
    [
        "cron_timezone: Missing/Zone",
        "cron_expression: broken",
        "report_states_list: Todo",
        "report_states_list: []",
        "report_states_list: [[Todo]]",
        "[]",
        "members_file_path: 42",
    ],
)
def test_invalid_config(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_config_from_file(path)


def test_shipped_examples_parse():
    root = Path(__file__).resolve().parents[1]
    load_config_from_file(root / "config.example.yaml")
    assert load_projects_from_file(root / "projects.example.json")
    assert load_members_from_file(root / "members.example.json") == {}
