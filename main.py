import os
from dotenv import load_dotenv

from api import PlaneAPI
from bot import PlaneNotifierBot
from utils import load_members_from_file, load_projects_from_file

if __name__ == '__main__':
    load_dotenv()
    workspace_slug = os.getenv('WORKSPACE_SLUG')
    api_token = os.getenv('API_TOKEN')
    base_url = os.getenv('BASE_URL')
    mode = os.getenv('MODE')
    bot_token = os.getenv('BOT_TOKEN')
    members_file_path = "members.json"
    projects_file_path = "projects.json"
    interval = 20 # seconds

    members_map = load_members_from_file(members_file_path)
    projects_map = load_projects_from_file(projects_file_path)
    plane_api = PlaneAPI(api_token, workspace_slug, members_map, base_url, mode)
    bot = PlaneNotifierBot(bot_token, projects_map, plane_api, interval, members_map)

    projects_data = plane_api.get_all_projects()
    # get_all_chats(bot_token)

    # for project in projects_data:
    #     project_id = project.get("id")
    #     if project_id:
    #         print(f"Fetching tasks for project: {project['name']} (ID: {project_id})")
    #         categorized_tasks = plane_api.get_tasks_by_status_for_project(project_id)
    #         report = plane_api.generate_report_for_project(project_id, categorized_tasks)
    #         # print(json.dumps(tasks, ensure_ascii=False, indent=4))

    # project_id = '610d57f1-107e-4da4-91a1-7c15022c16e1'
    # categorized_tasks = plane_api.get_tasks_by_status_for_project(project_id)
    # project_details = plane_api.get_project(project_id)
    # report = plane_api.generate_report_for_project(project_id, project_details, categorized_tasks)

    bot.run()