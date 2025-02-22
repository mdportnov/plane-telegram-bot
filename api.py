import json
import logging

import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure requests to use urllib3's logging
logging.getLogger('urllib3').setLevel(logging.INFO)
logging.getLogger('urllib3').propagate = True


class PlaneAPI:
    def __init__(self, api_token, workspace_slug, member_map, base_url='https://api.plane.so/', mode='debug'):
        self.mode = mode
        self.api_token = api_token
        self.workspace_slug = workspace_slug
        self.member_map = member_map
        self.base_url = base_url
        self.base_api_url = base_url + 'api/v1/'
        self.headers = {'X-API-Key': self.api_token}

    def get_all_projects(self):
        logging.log(logging.INFO, "Getting all projects")
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            if self.mode == 'debug':
                print(json.dumps(response.text, indent=4, ensure_ascii=False))
            projects = response.json()
            return [self.map_project(project) for project in projects.get("results", [])]
        else:
            print(f"Error fetching projects: {response.status_code}, {response.text}")
            return None

    def get_project(self, project_id):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            project = response.json()
            return self.map_project(project)
        else:
            print(f"Error fetching project: {response.status_code}, {response.text}")
            return None

    def get_project_tasks(self, project_id):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/issues/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching tasks for project {project_id}: {response.status_code}")
            return None

    def get_task_status_ids(self, project_id):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/states/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching task statuses for project {project_id}: {response.status_code}")
            return None

    def get_tasks_by_status_for_project(self, project_id):
        """
        Fetch tasks by statuses ('Todo', 'In Progress', 'In Review') for a specific project.

        Args:
            project_id (str): The ID of the project to process.

        Returns:
            dict: A dictionary containing tasks categorized by statuses.
        """
        # Fetch task statuses for the project
        task_statuses = self.get_task_status_ids(project_id)
        if not task_statuses:
            print(f"No statuses found for project ID: {project_id}")
            return

        if self.mode == 'debug':
            print(f"Task statuses: {task_statuses}")

        # Find IDs for required statuses
        todo_id = next((status["id"] for status in task_statuses["results"] if status["name"].lower() == "todo"), None)
        in_progress_id = next(
            (status["id"] for status in task_statuses["results"] if status["name"].lower() == "in progress"),
            None)
        in_review_id = next(
            (status["id"] for status in task_statuses["results"] if status["name"].lower() == "in review"), None)

        if not any([todo_id, in_progress_id, in_review_id]):
            print(f"No relevant statuses (Todo, In Progress, In Review) found for project ID: {project_id}")
            return

        # Fetch all tasks for the project
        tasks_data = self.get_project_tasks(project_id)
        if not tasks_data or "results" not in tasks_data:
            print(f"No tasks found for project ID: {project_id}")
            return

        # Filter tasks by status
        tasks = tasks_data["results"]
        todo_tasks = [task for task in tasks if task["state"] == todo_id]
        in_progress_tasks = [task for task in tasks if task["state"] == in_progress_id]
        in_review_tasks = [task for task in tasks if task["state"] == in_review_id]

        # Organize tasks into categories
        result = {
            "Todo": todo_tasks,
            "In Progress": in_progress_tasks,
            "In Review": in_review_tasks,
        }

        if self.mode == 'debug':
            logging.log(logging.INFO, json.dumps(result, indent=4, ensure_ascii=False))

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
        # Fetch tasks by status
        if not categorized_tasks:
            return f"No tasks found or failed to generate report for project ID: {project_id}"

        # Define the base URL for links
        project_base_url = f"{self.base_url}{self.workspace_slug}/projects/{project_id}/issues/"
        report = [f"📍*Project: {project_details['name']}*\n"]

        # Generate report for each status
        for status, tasks in categorized_tasks.items():
            report.append(f"*{status}*:")
            if not tasks:
                report.append("_No tasks_\n")
                continue

            for task in tasks:
                task_link = f"{project_base_url}{task['id']}"

                unique_assignees = set(task.get("assignees", []))

                assignees = ", ".join(
                    [self.member_map.get(user_id, f"[Unknown User]({user_id})") for user_id in unique_assignees]
                )

                report.append(
                    f"• [{task['name']}]({task_link})\n"
                    f"  └ Assigned to: {assignees if assignees else '_Unassigned_'}"
                )
            report.append("")

        if self.mode == 'debug':
            print("\n".join(report))

        return "\n".join(report)

    def create_issue(self, project_id, issue_data):
        url = f'{self.base_api_url}workspaces/{self.workspace_slug}/projects/{project_id}/issues/'
        response = requests.post(url, headers={**self.headers, "Content-Type": "application/json"}, data=json.dumps(issue_data))
        if response.status_code == 201:
            logging.info(f"Issue created successfully in project {project_id}.")
            return response.json()
        else:
            logging.error(f"Error creating issue in project {project_id}: {response.status_code}, {response.text}")
            return None

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
