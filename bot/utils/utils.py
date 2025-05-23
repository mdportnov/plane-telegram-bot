import json
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
success_emoji = "\u2705"
fail_emoji = "\u274c"


def load_members_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        members = json.load(file)
    return {member["member_id"]: f"{member['telegram_id']}" for member in members}


def load_projects_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        projects = json.load(file)
    return {project["project_id"]: f"{project['chat_id']}" for project in projects}


def escape_markdown_v2(text: str, chars = r'_*[]()~`>#+-=|{}.!') -> str:
    for char in chars:
        text = text.replace(char, '\\' + char)
    return text


def validate_dates(start_date, target_date, old_issue=None):
    try:
        print("TEST")
        if start_date:
            parsed_start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d')
            print(parsed_start_date)
        if target_date:
            parsed_target_date = datetime.datetime.strptime(target_date, '%Y-%m-%d')
            print(parsed_target_date)
        if start_date and target_date and parsed_target_date < parsed_start_date:
            return False
        if old_issue:
            old_start_date = datetime.datetime.strptime(old_issue["start_date"], '%Y-%m-%d') if old_issue[
                "start_date"] else None
            old_target_date = datetime.datetime.strptime(old_issue["target_date"], '%Y-%m-%d') if old_issue[
                "target_date"] else None
            if start_date and old_target_date and parsed_start_date > old_target_date:
                return False
            if target_date and old_start_date and parsed_target_date < old_start_date:
                return False
        return True
    except ValueError:
        return False


def html_to_markdownV2(html_text):
    # Заменяем основные теги
    replacements = [
        (r'<b>(.*?)</b>', r'*\1*'),
        (r'<i>(.*?)</i>', r'_\1_'),
        (r'<u>(.*?)</u>', r'__\1__'),
        (r'<s>(.*?)</s>', r'~\1~'),
        (r'<code>(.*?)</code>', r'`\1`'),
        (r'<pre>(.*?)</pre>', r'```\1```'),
        (r'<a href="(.*?)">(.*?)</a>', r'[\2](\1)'),
        (r'<br\s*/?>', '\n'),
        (r'<span>(.*?)</span>', r'\1'),  # Удаляем <span>, оставляя содержимое
        (r'<[^>]+>', ''),  # Удаляем все остальные теги
    ]

    for pattern, replacement in replacements:
        html_text = re.sub(pattern, replacement, html_text, flags=re.DOTALL)

    # Экранируем специальные символы MarkdownV2
    special_chars = r'_*[]()~`>#+-=|{}.!'
    for char in special_chars:
        html_text = html_text.replace(char, '\\' + char)

    return html_text.strip()
def load_config_from_file(file_path="config.yaml"):
    with open(file_path, 'r') as stream:
        data_loaded = yaml.safe_load(stream)
        return data_loaded
