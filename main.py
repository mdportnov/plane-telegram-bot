import os
from dotenv import load_dotenv

from api import PlaneAPI
from bot import PlaneNotifierBot

if __name__ == '__main__':
    load_dotenv()
    workspace_slug = 'command'
    api_token = os.getenv('API_TOKEN')
    base_url = os.getenv('BASE_URL')
    mode = os.getenv('MODE')
    bot_token = os.getenv('BOT_TOKEN')

    bot = PlaneNotifierBot(bot_token)
    plane_api = PlaneAPI(api_token, workspace_slug, base_url, mode)

    projects_data = plane_api.get_all_projects()

    # for project in projects_data:
    #     project_id = project.get("id")
    #     if project_id:
    #         print(f"Fetching tasks for project: {project['name']} (ID: {project_id})")
    #         categorized_tasks = plane_api.get_tasks_by_status_for_project(project_id)
    #         report = plane_api.generate_report_for_project(project_id, categorized_tasks)
    #         # print(json.dumps(tasks, ensure_ascii=False, indent=4))

    project_id = '610d57f1-107e-4da4-91a1-7c15022c16e1'
    categorized_tasks = plane_api.get_tasks_by_status_for_project(project_id)
    report = plane_api.generate_report_for_project(project_id, categorized_tasks)