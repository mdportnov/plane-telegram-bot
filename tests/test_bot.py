from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import Forbidden

from bot.bot import PlaneNotifierBot
from bot.service.api import PlaneAPI, PlaneAPIError

PROJECT = "af0d57f1-107e-4554-91a1-7c15022c16e1"
TASK = "12345678-1234-1234-1234-123456789abc"


@pytest.fixture
def bot():
    instance = PlaneNotifierBot.__new__(PlaneNotifierBot)
    instance.plane_api = Mock()
    instance.members_map = {}
    instance.project_to_chat_map = {PROJECT: "-100123"}
    instance.chat_to_project_map = {"-100123": PROJECT}
    instance.application = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    return instance


def update(text, chat_id=-100123):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=chat_id))


async def test_chat_id_before_mapping(bot):
    incoming = update("/chatid", -100456)
    await bot.chat_id(incoming, None)
    assert "-100456" in incoming.effective_message.reply_text.call_args.args[0]
    assert not bot.plane_api.mock_calls


@pytest.mark.parametrize(
    "handler", ["new_task", "update_task", "remove_task", "get_report", "get_states_list"]
)
async def test_unmapped_chats_cannot_access_plane(bot, handler):
    incoming = update("/command", -100456)
    await getattr(bot, handler)(incoming, None)
    assert "not configured" in incoming.effective_message.reply_text.call_args.args[0]
    assert not bot.plane_api.mock_calls


async def test_create_handler_sends_named_priority_and_escaped_description(bot):
    incoming = update("/newtask@MyBot\nTitle: Test\nPriority: 3\nDescription: <script>")
    bot.plane_api.task_summary.return_value = "Task"
    await bot.new_task(incoming, None)
    bot.plane_api.create_issue.assert_called_once_with(
        PROJECT,
        {
            "name": "Test",
            "priority": "high",
            "description_html": "<p>&lt;script&gt;</p>",
        },
    )
    bot.plane_api.map_states_by_ids.assert_not_called()
    assert incoming.effective_message.reply_text.call_args.kwargs["parse_mode"] == "HTML"


async def test_update_handler_preserves_omitted_fields(bot):
    incoming = update(f"/updatetask\nUUID: {TASK}\nTitle: Updated")
    bot.plane_api.get_task_by_uuid.return_value = {"assignees": ["existing"]}
    bot.plane_api.task_summary.return_value = "Task"
    await bot.update_task(incoming, None)
    bot.plane_api.update_issue.assert_called_once_with(PROJECT, TASK, {"name": "Updated"})


async def test_api_failure_is_not_reported_as_success(bot):
    incoming = update("/newtask\nTitle: Test")
    bot.plane_api.create_issue.side_effect = PlaneAPIError("Plane API returned HTTP 403.")
    await bot.new_task(incoming, None)
    assert "HTTP 403" in incoming.effective_message.reply_text.call_args.args[0]


async def test_scheduled_failure_does_not_prevent_other_chats(bot):
    bot.project_to_chat_map = {PROJECT: "-100123", TASK: "-100456"}
    bot._report = Mock(return_value=["report"])
    bot.application.bot.send_message.side_effect = [Forbidden("blocked"), None]
    await bot.send_report_to_chats()
    assert bot.application.bot.send_message.await_count == 2
    assert bot.application.bot.send_message.call_args.kwargs["chat_id"] == "-100456"


async def test_plane_failure_does_not_prevent_other_chats(bot):
    bot.project_to_chat_map = {PROJECT: "-100123", TASK: "-100456"}
    bot._report = Mock(side_effect=[PlaneAPIError("offline"), ["report"]])
    await bot.send_report_to_chats()
    bot.application.bot.send_message.assert_awaited_once_with(
        chat_id="-100456", text="report", parse_mode="HTML"
    )


async def test_empty_scheduled_report_is_skipped(bot):
    bot.plane_api.get_tasks_by_status_for_project.return_value = {"Todo": []}
    assert bot._report(PROJECT, True) == []
    bot.plane_api.generate_report_for_project.assert_not_called()


@pytest.mark.parametrize("text", [f"/removetask {TASK}", f"/removetask@MyBot\nUUID: {TASK}"])
async def test_delete_formats(bot, text):
    incoming = update(text)
    await bot.remove_task(incoming, None)
    bot.plane_api.remove_issue.assert_called_once_with(PROJECT, TASK)


async def test_full_report_handler_splits_output(bot):
    real_api = PlaneAPI("secret", "acme")
    real_api.get_project = Mock(return_value={"name": "Project"})
    real_api.get_tasks_by_status_for_project = Mock(
        return_value={"Todo": [{"id": TASK, "name": "Task" * 60} for _ in range(50)]}
    )
    bot.plane_api = real_api
    incoming = update("/getreport")
    await bot.get_report(incoming, None)
    assert incoming.effective_message.reply_text.await_count > 1
    assert (
        sum(call.args[0].count("UUID:") for call in incoming.effective_message.reply_text.call_args_list)
        == 50
    )


async def test_scheduler_uses_application_lifecycle_and_configured_timezone():
    instance = PlaneNotifierBot("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789")
    await instance._start_scheduler(instance.application)
    assert instance.scheduler is None
    instance.project_to_chat_map = {PROJECT: "-123"}
    instance.config = {"cron_expression": "0 9 * * mon-fri", "cron_timezone": "Africa/Johannesburg"}
    await instance._start_scheduler(instance.application)
    assert instance.scheduler.running
    job = instance.scheduler.get_jobs()[0]
    assert str(job.trigger.timezone) == "Africa/Johannesburg"
    assert job.max_instances == 1
    await instance._stop_scheduler(instance.application)
