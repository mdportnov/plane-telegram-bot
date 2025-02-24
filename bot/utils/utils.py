import json
import logging
import re
import datetime
import yaml

# Priority map
index_to_priority = {
    '0': "none",
    '1': "low",
    '2': "medium",
    '3': "high",
    '4': "urgent",
}
success_emoji= "\u2705"
fail_emoji = "\u274c"

def load_members_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        members = json.load(file)
    return {member["member_id"]: f"{member['telegram_id']}" for member in members}

def load_projects_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        projects = json.load(file)
    return {project["project_id"]: f"{project['chat_id']}" for project in projects}

def escape_markdown_v2(text: str,chars = "\\_*[\]()~`>#+\-=\|{}.!") -> str:
    special_chars = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(rf"([{chars}])", r"\\\1", text)

def validate_dates(start_date, target_date, old_issue=None):
    try:
        if start_date:
            parsed_start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        if target_date:
            parsed_target_date = datetime.datetime.strptime(target_date, '%Y-%m-%d')
        if start_date and target_date and parsed_target_date < parsed_start_date:
            return False
        if old_issue:
            old_start_date = datetime.datetime.strptime(old_issue["start_date"], '%Y-%m-%d') if old_issue["start_date"] else None
            old_target_date = datetime.datetime.strptime(old_issue["target_date"], '%Y-%m-%d') if old_issue["target_date"] else None
            if start_date and old_target_date and parsed_start_date > old_target_date:
                return False
            if target_date and old_start_date and parsed_target_date < old_start_date:
                return False
        return True
    except ValueError:
        return False

def load_config_from_file(file_path="config.yaml"):
    with open(file_path, 'r') as stream:
        data_loaded = yaml.safe_load(stream)
        return data_loaded
