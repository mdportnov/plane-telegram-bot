from unittest.mock import Mock, patch
from xml.etree import ElementTree

import pytest
import requests

from bot.service.api import PlaneAPI, PlaneAPIError

PROJECT = "af0d57f1-107e-4554-91a1-7c15022c16e1"
TASK = "12345678-1234-1234-1234-123456789abc"


@pytest.fixture
def api():
    return PlaneAPI("secret", "acme", {"report_states_list": ["Todo"]})


def response(data=None, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


@patch("bot.service.api.requests.request")
def test_cursor_pagination(request, api):
    request.side_effect = [
        response({"results": [{"id": "one"}], "next_page_results": True, "next_cursor": "20:1:0"}),
        response({"results": [{"id": "two"}], "next_page_results": False}),
    ]
    assert api.get_project_tasks(PROJECT) == [{"id": "one"}, {"id": "two"}]
    first, second = request.call_args_list
    assert first.args[1].endswith(f"/projects/{PROJECT}/work-items/")
    assert first.kwargs["headers"] == {"X-API-Key": "secret"}
    assert first.kwargs["timeout"] == (5, 30)
    assert first.kwargs["allow_redirects"] is False
    assert first.kwargs["params"] == {}
    assert second.kwargs["params"] == {"cursor": "20:1:0"}


@pytest.mark.parametrize("listing", ["get_all_projects", "get_members", "get_task_states_ids"])
@patch("bot.service.api.requests.request")
def test_all_list_endpoints_follow_pagination(request, listing, api):
    request.side_effect = [
        response({"results": [{"id": "one"}], "next_page_results": True, "next_cursor": "next"}),
        response({"results": [{"id": "two"}], "next_page_results": False}),
    ]
    args = (PROJECT,) if listing == "get_task_states_ids" else ()
    assert len(getattr(api, listing)(*args)) == 2


@patch("bot.service.api.requests.request")
def test_members_and_states_accept_arrays(request, api):
    request.return_value = response([{"id": TASK, "name": "Todo"}])
    assert api.map_states_by_ids(PROJECT) == {TASK: "Todo"}
    assert api.get_members(PROJECT)[0]["id"] == TASK
    assert request.call_args.args[1].endswith("/project-members/")
    api.get_members()
    assert request.call_args.args[1].endswith("/workspaces/acme/members/")


@patch("bot.service.api.requests.request")
def test_repeated_cursor_fails_instead_of_looping(request, api):
    request.return_value = response({"results": [], "next_page_results": True, "next_cursor": "same"})
    with pytest.raises(PlaneAPIError, match="pagination"):
        api.get_all_projects()
    assert request.call_count == 2


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
@patch("bot.service.api.requests.request")
def test_api_errors_are_actionable_without_leaking_body(request, status, api):
    request.return_value = response({"secret": "private"}, status)
    with pytest.raises(PlaneAPIError, match=f"HTTP {status}") as caught:
        api.get_all_projects()
    assert "private" not in str(caught.value)
    assert request.call_count == 1


@patch("bot.service.api.requests.request")
def test_timeout_does_not_retry_creation(request, api):
    request.side_effect = requests.Timeout("secret")
    with pytest.raises(PlaneAPIError, match="before repeating"):
        api.create_issue(PROJECT, {"name": "Example"})
    assert request.call_count == 1


@patch("bot.service.api.requests.request")
def test_invalid_json(request, api):
    request.return_value = response()
    request.return_value.json.side_effect = ValueError("HTML")
    with pytest.raises(PlaneAPIError, match="invalid JSON"):
        api.get_all_projects()


@pytest.mark.parametrize("endpoint", ["work-items", "issues"])
@patch("bot.service.api.requests.request")
def test_all_task_operations_share_endpoint_and_trailing_slash(request, endpoint):
    api = PlaneAPI("secret", "acme", base_url="https://plane.example.com", work_items_endpoint=endpoint)
    request.return_value = response({"id": TASK}, 201)
    assert api.create_issue(PROJECT, {"name": "Name", "priority": "high"}) == {"id": TASK}
    assert request.call_args.args == (
        "POST",
        f"https://plane.example.com/api/v1/workspaces/acme/projects/{PROJECT}/{endpoint}/",
    )
    assert request.call_args.kwargs["json"]["priority"] == "high"
    request.return_value = response({"id": TASK})
    api.update_issue(PROJECT, TASK, {"name": "Next"})
    assert request.call_args.args[0] == "PATCH"
    assert request.call_args.args[1].endswith(f"/{endpoint}/{TASK}/")
    api.get_task_by_uuid(PROJECT, TASK)
    assert request.call_args.args[0] == "GET"
    request.return_value = response(status=204)
    assert api.remove_issue(PROJECT, TASK) is None
    assert request.call_args.args[0] == "DELETE"
    assert request.call_args.args[1].endswith(f"/{endpoint}/{TASK}/")
    request.return_value.json.assert_not_called()


def test_cloud_and_self_hosted_links(api):
    assert api.task_url(PROJECT, TASK).startswith("https://app.plane.so/acme/")
    own = PlaneAPI("secret", "acme", base_url="https://plane.example.com/")
    assert own.task_url(PROJECT, TASK).startswith("https://plane.example.com/acme/")
    separate = PlaneAPI(
        "secret", "acme", base_url="https://api.example.com", app_url="https://app.example.com"
    )
    assert separate.task_url(PROJECT, TASK).startswith("https://app.example.com/acme/")


@pytest.mark.parametrize(
    "url", ["ftp://host", "https://user:pass@host", "https://host/api/v1", "https://host/?key=x"]
)
def test_invalid_base_urls(url):
    with pytest.raises(ValueError):
        PlaneAPI("secret", "acme", base_url=url)


def test_long_reports_are_split_at_html_boundaries(api):
    tasks = [{"id": TASK, "name": '<>&"😀' * 51, "assignees": ["unknown_member"]} for _ in range(40)]
    messages = api.generate_report_for_project(PROJECT, {"name": "R&D <Team>"}, {"Todo": tasks})
    assert len(messages) > 1
    assert sum(message.count("UUID:") for message in messages) == 40
    for message in messages:
        root = ElementTree.fromstring("<root>" + message + "</root>")
        assert len("".join(root.itertext()).encode("utf-16-le")) // 2 <= 4096
    assert "unknown_member" in messages[0]


def test_nullable_assignees(api):
    assert "Unassigned" in api.task_summary(PROJECT, {"id": TASK, "name": "Task", "assignees": None})


def test_task_filter_supports_expanded_state(api):
    api.map_states_by_ids = Mock(return_value={"todo": "Todo", "done": "Done"})
    api.get_project_tasks = Mock(return_value=[{"state": {"id": "todo"}}, {"state": "done"}])
    assert api.get_tasks_by_status_for_project(PROJECT) == {"Todo": [{"state": {"id": "todo"}}]}


def test_report_limits_count_astral_unicode_and_html_after_parsing(api):
    tasks = [
        {
            "id": TASK,
            "name": "😀" * 255,
            "assignees": [{"id": "unmapped", "display_name": "😀<&" * 400}],
        }
        for _ in range(10)
    ]
    messages = api.generate_report_for_project(PROJECT, {"name": "😀" * 255}, {"😀" * 255: tasks})
    for message in messages:
        root = ElementTree.fromstring("<root>" + message + "</root>")
        assert len("".join(root.itertext()).encode("utf-16-le")) // 2 <= 4096
    assert sum(message.count("UUID:") for message in messages) == 10
