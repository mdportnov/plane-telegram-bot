import datetime
import json
import re
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from apscheduler.triggers.cron import CronTrigger

index_to_priority = {"0": "none", "1": "low", "2": "medium", "3": "high", "4": "urgent"}


def validate_uuid(value, label="UUID"):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{label} must be a UUID, not a name or short identifier.") from None


def load_json_list(file_path):
    try:
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(
            f"Cannot read {file_path}. Create a valid JSON file using the example in README.md."
        ) from None
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError(f"{file_path} must contain a JSON array of objects.")
    return data


def load_members_from_file(file_path):
    if file_path is None:
        return {}
    result = {}
    usernames = set()
    for member in load_json_list(file_path):
        member_id = validate_uuid(member.get("member_id"), f"{file_path}: member_id")
        username = str(member.get("telegram_id", "")).strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", username):
            raise ValueError(f"{file_path}: telegram_id must be a Telegram username, with or without @.")
        if member_id in result or username.lower() in usernames:
            raise ValueError(f"{file_path}: duplicate member_id or Telegram username.")
        result[member_id] = username
        usernames.add(username.lower())
    return result


def load_projects_from_file(file_path):
    result = {}
    chats = set()
    for project in load_json_list(file_path):
        project_id = validate_uuid(project.get("project_id"), f"{file_path}: project_id")
        chat_id = str(project.get("chat_id", ""))
        if not re.fullmatch(r"-?[1-9][0-9]*", chat_id):
            raise ValueError(f"{file_path}: chat_id must be a numeric Telegram chat ID. Use /chatid.")
        if project_id in result or chat_id in chats:
            raise ValueError(f"{file_path}: use one unique project per unique chat.")
        result[project_id] = chat_id
        chats.add(chat_id)
    return result


def normalize_date(value):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(value, fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    raise ValueError("Invalid date. Use YYYY-MM-DD or DD-MM-YYYY.")


def validate_dates(start_date, target_date, old_issue=None):
    old_issue = old_issue or {}
    start = start_date if start_date is not None else old_issue.get("start_date")
    end = target_date if target_date is not None else old_issue.get("target_date")
    try:
        start = datetime.date.fromisoformat(start) if start else None
        end = datetime.date.fromisoformat(end) if end else None
        return not (start and end and start > end)
    except (ValueError, TypeError):
        return False


def load_config_from_file(file_path="config.yaml"):
    path = Path(file_path)
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise ValueError(
            f"Cannot read {file_path}. Copy config.example.yaml to config.yaml and edit it."
        ) from None
    if not isinstance(config, dict):
        raise ValueError(f"{file_path} must contain a YAML mapping.")
    config = {
        "report_states_list": ["Todo", "In Progress", "In Review"],
        "cron_expression": "0 9 * * mon-fri",
        "cron_timezone": "UTC",
        "projects_file_path": "projects.json",
        "members_file_path": None,
        **config,
    }
    states = config["report_states_list"]
    if (
        not isinstance(states, list)
        or not states
        or any(not isinstance(s, str) or not s.strip() for s in states)
    ):
        raise ValueError("report_states_list must be a non-empty list of state names.")
    try:
        ZoneInfo(config["cron_timezone"])
        CronTrigger.from_crontab(config["cron_expression"], timezone=config["cron_timezone"])
    except (ValueError, TypeError, KeyError, AttributeError, ZoneInfoNotFoundError):
        raise ValueError(
            "Invalid cron_expression or cron_timezone. Use a five-field cron and an IANA timezone."
        ) from None
    for key in ("projects_file_path", "members_file_path"):
        value = config[key]
        if value is None and key == "members_file_path":
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a file path.")
        config[key] = str(path.parent / value)
    return config
