import re
from html import escape

from bot.utils.utils import index_to_priority, normalize_date, validate_dates, validate_uuid

FIELDS = {"UUID", "Title", "Description", "Start", "Deadline", "Priority", "State", "Assignees"}


def parse_task_message(message):
    fields = {}
    current = None
    for line in message.splitlines()[1:]:
        match = re.match(r"^([A-Za-z]+)\s*:\s*(.*)$", line)
        if match and match[1] in FIELDS:
            current = match[1]
            if current in fields:
                raise ValueError(f"Duplicate field: {current}.")
            fields[current] = match[2].strip()
        elif re.fullmatch(r"\s*@\w+(?:[\s,]+@\w+)*\s*", line):
            fields["Assignees"] = (fields.get("Assignees", "") + " " + line.strip()).strip()
            current = None
        elif current == "Description":
            fields[current] += "\n" + line
        elif line.strip():
            raise ValueError("Unknown field or unexpected text. Use /help for the command format.")
    return fields


def build_task_data(fields, members, states=None, old_task=None):
    data = {}
    if old_task is None or "Title" in fields:
        title = fields.get("Title", "").strip()
        if not 1 <= len(title) <= 255:
            raise ValueError("Title is required and must contain 1–255 characters.")
        data["name"] = title
    if "Description" in fields:
        data["description_html"] = "<p>" + escape(fields["Description"]).replace("\n", "<br>") + "</p>"
    for field, key in (("Start", "start_date"), ("Deadline", "target_date")):
        if field in fields:
            data[key] = normalize_date(fields[field])
    if not validate_dates(data.get("start_date"), data.get("target_date"), old_task):
        raise ValueError("Deadline must be on or after Start, including dates already on the task.")
    if "Priority" in fields:
        priority = index_to_priority.get(fields["Priority"])
        if priority is None:
            raise ValueError("Priority must be 0 (none), 1 (low), 2 (medium), 3 (high), or 4 (urgent).")
        data["priority"] = priority
    if "State" in fields:
        state_id = next((key for key, value in (states or {}).items() if value == fields["State"]), None)
        if not state_id:
            raise ValueError("Unknown State. Run /getstates for exact names.")
        data["state"] = state_id
    if "Assignees" in fields:
        mentions = fields["Assignees"].replace(",", " ").split()
        inverse = {name.lstrip("@").lower(): key for key, name in members.items()}
        ids = []
        for mention in mentions:
            if not mention.startswith("@") or mention[1:].lower() not in inverse:
                raise ValueError(
                    f"Unknown assignee {mention}. Add their Plane ID and Telegram username to members.json."
                )
            ids.append(inverse[mention[1:].lower()])
        if not ids:
            raise ValueError("Assignees must contain at least one @username.")
        existing = (old_task or {}).get("assignees") or []
        existing = [item["id"] if isinstance(item, dict) else item for item in existing]
        data["assignees"] = list(dict.fromkeys(existing + ids))
    if old_task is not None and not data:
        raise ValueError("Provide at least one field to update after UUID.")
    return data


def task_id_from_fields(fields):
    return validate_uuid(fields.get("UUID"), "Task UUID")
