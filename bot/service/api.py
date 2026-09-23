import re
from html import escape, unescape
from urllib.parse import quote, urlsplit

import requests

from bot.utils.utils import validate_uuid


class PlaneAPIError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def telegram_text_length(message):
    text = unescape(re.sub(r"<[^>]+>", "", message))
    return len(text.encode("utf-16-le")) // 2


def normalize_base_url(value, label):
    value = value.rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be an http(s) URL without credentials, query, or fragment.")
    if parsed.path.rstrip("/").endswith("/api/v1"):
        raise ValueError(f"{label} must be the server URL without /api/v1.")
    return value + "/"


class PlaneAPI:
    def __init__(
        self,
        api_token,
        workspace_slug,
        config=None,
        member_map=None,
        base_url="https://api.plane.so/",
        mode="INFO",
        app_url=None,
        work_items_endpoint="work-items",
    ):
        self.mode = mode
        self.config = config or {}
        self.member_map = member_map or {}
        self.workspace_slug = workspace_slug
        self.base_url = normalize_base_url(base_url, "BASE_URL")
        self.app_url = normalize_base_url(
            app_url
            or ("https://app.plane.so" if self.base_url == "https://api.plane.so/" else self.base_url),
            "PLANE_APP_URL",
        )
        if work_items_endpoint not in ("work-items", "issues"):
            raise ValueError("PLANE_WORK_ITEMS_ENDPOINT must be work-items or issues.")
        self.work_items_endpoint = work_items_endpoint
        self.base_api_url = f"{self.base_url}api/v1/workspaces/{quote(workspace_slug, safe='')}/"
        self.headers = {"X-API-Key": api_token}

    def _request(self, method, path, **kwargs):
        try:
            response = requests.request(
                method,
                self.base_api_url + path,
                headers=self.headers,
                timeout=(5, 30),
                allow_redirects=False,
                **kwargs,
            )
        except requests.Timeout:
            raise PlaneAPIError(
                "Plane request timed out. Check Plane before repeating a write command."
            ) from None
        except requests.RequestException:
            raise PlaneAPIError("Cannot connect to Plane. Check BASE_URL and network access.") from None
        if not 200 <= response.status_code < 300:
            hints = {
                400: "Plane rejected the data. Check state, priority, dates and project membership.",
                401: "Check API_TOKEN; it may be invalid or expired.",
                403: "The API token does not have access to this workspace or project.",
                404: "Check workspace/project/task IDs and PLANE_WORK_ITEMS_ENDPOINT for older servers.",
                429: "Plane rate limit reached. Wait before retrying.",
            }
            hint = hints.get(response.status_code, "Check the Plane server and BASE_URL.")
            raise PlaneAPIError(
                f"Plane API returned HTTP {response.status_code}. {hint}", response.status_code
            )
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError:
            raise PlaneAPIError(
                "Plane returned invalid JSON. BASE_URL must point to the API server."
            ) from None

    def _list(self, path):
        results = []
        params = {}
        seen = set()
        while True:
            data = self._request("GET", path, params=dict(params))
            if isinstance(data, list):
                return results + data
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise PlaneAPIError("Unexpected Plane list response; expected an array or results array.")
            results.extend(data["results"])
            if not data.get("next_page_results"):
                return results
            cursor = data.get("next_cursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise PlaneAPIError("Plane returned an invalid pagination cursor; report is incomplete.")
            seen.add(cursor)
            params["cursor"] = cursor

    def _project_path(self, project_id):
        return f"projects/{validate_uuid(project_id, 'project_id')}/"

    def _task_path(self, project_id, task_id=None):
        path = f"{self._project_path(project_id)}{self.work_items_endpoint}/"
        return path + f"{validate_uuid(task_id, 'task UUID')}/" if task_id else path

    def get_all_projects(self):
        return self._list("projects/")

    def get_project(self, project_id):
        return self._request("GET", self._project_path(project_id))

    def get_members(self, project_id=None):
        path = f"{self._project_path(project_id)}project-members/" if project_id else "members/"
        return self._list(path)

    def get_project_tasks(self, project_id):
        return self._list(self._task_path(project_id))

    def get_task_by_uuid(self, project_id, issue_id):
        return self._request("GET", self._task_path(project_id, issue_id))

    def get_task_states_ids(self, project_id):
        return self._list(f"{self._project_path(project_id)}states/")

    def map_states_by_ids(self, project_id):
        return {state["id"]: state["name"] for state in self.get_task_states_ids(project_id)}

    def get_tasks_by_status_for_project(self, project_id):
        states = self.map_states_by_ids(project_id)
        wanted = self.config.get("report_states_list", ["Todo", "In Progress", "In Review"])
        selected = {key: value for key, value in states.items() if value in wanted}
        if not selected:
            raise PlaneAPIError(
                "No report states match this project. Run /getstates and edit report_states_list."
            )
        result = {name: [] for name in wanted if name in selected.values()}
        for task in self.get_project_tasks(project_id):
            state = task.get("state")
            state = state.get("id") if isinstance(state, dict) else state
            if state in selected:
                result[selected[state]].append(task)
        return result

    def task_url(self, project_id, task_id):
        return (
            f"{self.app_url}{quote(self.workspace_slug, safe='')}/projects/"
            f"{validate_uuid(project_id)}/issues/{validate_uuid(task_id)}/"
        )

    def task_summary(self, project_id, task):
        names = []
        for assignee in task.get("assignees") or []:
            user_id = assignee.get("id") if isinstance(assignee, dict) else assignee
            username = self.member_map.get(user_id)
            name = "@" + username.lstrip("@") if username else user_id
            if isinstance(assignee, dict) and not username:
                name = assignee.get("display_name") or user_id
            names.append(str(name))
        assignees = ", ".join(dict.fromkeys(names)) or "Unassigned"
        return (
            f'<a href="{escape(self.task_url(project_id, task["id"]), quote=True)}">'
            f"{escape(str(task['name'])[:255])}</a>\n"
            f"UUID: <code>{escape(task['id'])}</code>\n"
            f"Assigned to: {escape(assignees[:1000])}"
        )

    def generate_report_for_project(self, project_id, project_details, categorized_tasks):
        header = f"<b>Project: {escape(str(project_details['name'])[:255])}</b>"
        messages = []
        current = header
        for status, tasks in categorized_tasks.items():
            blocks = [f"<b>{escape(status[:255])}</b>"]
            blocks += [self.task_summary(project_id, task) for task in tasks] or ["No tasks"]
            for block in blocks:
                if telegram_text_length(current + "\n\n" + block) > 3800:
                    messages.append(current)
                    current = header
                current += "\n\n" + block
        messages.append(current)
        return messages

    def create_issue(self, project_id, issue_data):
        return self._request("POST", self._task_path(project_id), json=issue_data)

    def update_issue(self, project_id, issue_id, issue_data):
        return self._request("PATCH", self._task_path(project_id, issue_id), json=issue_data)

    def remove_issue(self, project_id, issue_id):
        return self._request("DELETE", self._task_path(project_id, issue_id))
