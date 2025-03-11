import json


import requests

from bot.utils.logger_config import logger
from bot.utils.utils import escape_markdown_v2


class PlaneAPI:
    def __init__(self, api_token, workspace_slug,config, member_map, base_url='https://api.plane.so/', mode='debug'):
        self.mode = mode
        self.api_token = api_token
        self.workspace_slug = workspace_slug
        self.member_map = member_map
        self.config = config
        self.base_url = base_url
        self.base_api_url = base_url + 'api/v1/'
        self.headers = {'X-API-Key': self.api_token}

    def get_all_projects(self):
        logger.info("Getting all projects")
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/'
        response = requests.get(url, headers=self.headers)
        logger.debug(json.dumps(response.text, indent=4, ensure_ascii=False))
        if response.status_code == 200:
            projects = response.json()
            return [self.map_project(project) for project in projects.get("results", [])]
        else:
            logger.error(f"Error fetching projects: {response.status_code}, {response.text}")
            return None

    def get_project(self, project_id):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/'
        response = requests.get(url, headers=self.headers)
        logger.debug(json.dumps(response.text, indent=4, ensure_ascii=False))
        if response.status_code == 200:
            logger.info(f"Successfully received project{project_id}.")
            project = response.json()
            return self.map_project(project)
        else:
            logger.error(f"Error fetching project: {response.status_code}, {response.text}")
            return None

    def get_project_tasks(self, project_id):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/issues/'
        response = requests.get(url, headers=self.headers)
        logger.debug(json.dumps(response.text, indent=4, ensure_ascii=False))
        if response.status_code == 200:
            logger.info(f"Successfully received tasks for project{project_id}.")
            return response.json()
        else:
            logger.error(f"Error fetching tasks for project {project_id}: {response.status_code}")
            return None
    def get_task_by_uuid(self, project_id,issue_id):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/issues/{issue_id}'
        response = requests.get(url, headers=self.headers)
        logger.debug(json.dumps(response.text, indent=4, ensure_ascii=False))
        if response.status_code == 200:
            logger.info(f"Successfully received issue{issue_id}.")
            return response.json()
        else:
            logger.error(f"Error fetching task from project {project_id}: {response.status_code}")
            return None
    def get_task_states_ids(self, project_id):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/states/'
        response = requests.get(url, headers=self.headers)
        logger.debug(json.dumps(response.text, indent=4, ensure_ascii=False))
        if response.status_code == 200:
            logger.info(f"Successfully received states{project_id}.")
            return response.json()
        else:
            logger.error(f"Error fetching task statuses for project {project_id}: {response.status_code}")
            return None

    def get_tasks_by_status_for_project(self, project_id):
        """
        Fetch tasks by statuses ('Todo', 'In Progress', 'In Review') for a specific project.

        Args:
            project_id (str): The ID of the project to process.

        Returns:
            dict: A dictionary containing tasks categorized by statuses.
        """
        states_list = self.config["report_states_list"]
        #Fetch project states
        project_states_map =  self.map_states_by_ids(project_id)
        if not project_states_map:
            logger.warning(f"No statuses found for project ID: {project_id}")
            return
        inv_project_states_map = { v : k  for k,v in project_states_map.items() }

        # Task states filter
        report_states_map = {inv_project_states_map[item] : item for item in inv_project_states_map.keys() if item in states_list }
        if not report_states_map:
            logger.warning(f"No relevant statuses found for project ID: {project_id}")
            return
        # Fetch all tasks for the project
        tasks_data = self.get_project_tasks(project_id)
        if not tasks_data or "results" not in tasks_data:
            logger.warning(f"No tasks found for project ID: {project_id}")
            return
        # Construct categorized tasks
        result = {
            state_name : [task for task in tasks_data["results"] if task["state"] == state_id] for state_id ,state_name in report_states_map.items()
        }

        return result

    def generate_report_for_project(self, project_id, project_details, categorized_tasks):
        """
        Generate a formatted report for tasks categorized by statuses ('Todo', 'In Progress', 'In Review')
        for a specific project, with links to issues and users for Telegram bot output.

        Args:
            categorized_tasks (dict): tasks categorized by statuses.
            project_details (dict): details about the project.
            project_id (str): The ID of the project to process.

        Returns:
            str: A formatted report string for Telegram.
        """
        md_v2 = escape_markdown_v2
        # Fetch tasks by status
        if not categorized_tasks:
            return f"No tasks found or failed to generate report for project ID: {project_id}"

        # Define the base URL for links
        project_base_url = f"{self.base_url}{self.workspace_slug}/projects/{project_id}/issues/"
        report = [f"📍*Project: {md_v2(project_details['name'])}*\n"]
        # Generate report for each status
        for status, tasks in categorized_tasks.items():
            report.append(f"*{md_v2(status)}*:")
            if not tasks:
                report.append("_No tasks_\n")
                continue

            for task in tasks:
                task_link = f"{project_base_url}{(task['id'])}"
                unique_assignees = set(task.get("assignees", []))
                assignees = ", ".join(
                    ['@'+self.member_map.get(user_id) for user_id in unique_assignees]
                )
                report.append(
                    f"• [{md_v2(task['name'])}]({md_v2(task_link)})\n"
                    f"  └ Assigned to: {md_v2(assignees) if assignees else '_Unassigned_'}"
                )
            report.append("")

        logger.debug("\n".join(report))
        return "\n".join(report)

    def create_issue(self, project_id, issue_data):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/issues/'
        response = requests.post(url, headers={**self.headers, "Content-Type": "application/json"}, data=json.dumps(issue_data))
        logger.debug(json.dumps(response.text, indent=4, ensure_ascii=False))
        if response.status_code == 201:
            logger.info(f"Issue created successfully in project {project_id}.")
            return response.json()
        else:
            logger.error(f"Error creating issue in project {project_id}: {response.status_code}, {response.text}")
            return None

    def update_issue(self,project_id,issue_id, update_issue_data):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/issues/{issue_id}/'
        response = requests.patch(url, headers={**self.headers, "Content-Type": "application/json"}, data=json.dumps(update_issue_data))
        logger.debug(json.dumps(response.text, indent=4, ensure_ascii=False))
        if response.status_code == 200:
            logger.info(f"Issue update successfully in project {project_id}.")
            return response.json()
        else:
            logger.error(f"Error updating issue in project {project_id}: {response.status_code}, {response.text}")
            return None

    def map_states_by_ids(self,project_id):
        states = self.get_task_states_ids(project_id)
        mapped_statutes = {
            data["id"]: data["name"] for data in states["results"]
        }
        return mapped_statutes

    @staticmethod
    def map_project_members(project_details):
        return {
            member["member_id"]: f"{member['member__display_name']}"
            for member in project_details.get("members", [])
        }

    @staticmethod
    def map_project(project):
        return {
            "id": project.get("id"),
            "name": project.get("name"),
            "identifier": project.get("identifier"),
            "project_lead": project.get("project_lead"),
            "default_state": project.get("default_state"),
            "members": project.get("members")
        }
