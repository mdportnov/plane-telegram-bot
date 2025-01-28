import json


def load_members_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        members = json.load(file)
    return {member["member_id"]: f"{member['telegram_id']}" for member in members}

def load_projects_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        projects = json.load(file)
    return {project["project_id"]: f"{project['chat_id']}" for project in projects}
