import asyncio
from functools import wraps

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import AIORateLimiter, Application, CommandHandler, ContextTypes

from bot.commands import build_task_data, parse_task_message, task_id_from_fields
from bot.service.api import PlaneAPIError
from bot.utils.logger_config import logger
from bot.utils.utils import validate_uuid

HELP = (
    "/chatid — show this Telegram chat ID\n"
    "/getstates — list Plane state names and IDs\n"
    "/getreport — report for this chat’s project\n"
    "/newtask — create a task (Title required)\n"
    "/updatetask — update a task (UUID required)\n"
    "/removetask <UUID> — permanently delete a task\n\n"
    "Put each field on its own line:\n"
    "/newtask\nTitle: Prepare release\nDescription: Release notes\n"
    "Start: 2026-10-01\nDeadline: 2026-10-05\nPriority: 3\n"
    "State: In Progress\nAssignees: @alice\n\n"
    "All fields except Title are optional for /newtask.\n"
    "For /updatetask, use UUID: <task UUID> and only the fields to change.\n"
    "Assignees are added to existing assignees. Use Plane to remove them.\n"
    "Priority: 0=none, 1=low, 2=medium, 3=high, 4=urgent.\n"
    "Dates: YYYY-MM-DD or DD-MM-YYYY.\n"
    "Setup: run python main.py --help on the bot host."
)


def project_command(handler):
    @wraps(handler)
    async def wrapped(self, update, context):
        if update.effective_message is None or update.effective_chat is None:
            return
        project_id = self.chat_to_project_map.get(str(update.effective_chat.id))
        if not project_id:
            await update.effective_message.reply_text(
                "This chat is not configured. Use /chatid, add it to projects.json, and restart the bot."
            )
            return
        try:
            await handler(self, update, context, project_id)
        except (ValueError, PlaneAPIError) as error:
            await update.effective_message.reply_text(str(error))

    return wrapped


class PlaneNotifierBot:
    def __init__(self, bot_token, plane_api=None, config=None, members_map=None, projects_map=None):
        self.plane_api = plane_api
        self.config = config or {}
        self.members_map = members_map or {}
        self.project_to_chat_map = projects_map or {}
        self.chat_to_project_map = {str(chat): project for project, chat in self.project_to_chat_map.items()}
        self.scheduler = None
        self.application = (
            Application.builder()
            .token(bot_token)
            .rate_limiter(AIORateLimiter(max_retries=2))
            .post_init(self._start_scheduler)
            .post_stop(self._stop_scheduler)
            .build()
        )
        for command, handler in (
            ("start", self.help),
            ("help", self.help),
            ("chatid", self.chat_id),
            ("newtask", self.new_task),
            ("updatetask", self.update_task),
            ("removetask", self.remove_task),
            ("getstates", self.get_states_list),
            ("getreport", self.get_report),
        ):
            self.application.add_handler(CommandHandler(command, handler))
        self.application.add_error_handler(self.on_error)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text(HELP)

    async def chat_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text(
            f"Chat ID: {update.effective_chat.id}\nUse this as chat_id in projects.json."
        )

    @project_command
    async def get_states_list(self, update, context, project_id):
        states = await asyncio.to_thread(self.plane_api.map_states_by_ids, project_id)
        for name, state_id in ((name, state_id) for state_id, name in states.items()):
            await update.effective_message.reply_text(f"{name}\n{state_id}")
        if not states:
            await update.effective_message.reply_text("This project has no states.")

    def _create_task(self, project_id, fields):
        states = self.plane_api.map_states_by_ids(project_id) if "State" in fields else None
        data = build_task_data(fields, self.members_map, states)
        return self.plane_api.create_issue(project_id, data)

    @project_command
    async def new_task(self, update, context, project_id):
        fields = parse_task_message(update.effective_message.text)
        if "UUID" in fields:
            raise ValueError("Use /updatetask to change an existing UUID.")
        task = await asyncio.to_thread(self._create_task, project_id, fields)
        await update.effective_message.reply_text(
            "Task created.\n" + self.plane_api.task_summary(project_id, task), parse_mode="HTML"
        )

    def _update_task(self, project_id, fields):
        task_id = task_id_from_fields(fields)
        old = self.plane_api.get_task_by_uuid(project_id, task_id)
        states = self.plane_api.map_states_by_ids(project_id) if "State" in fields else None
        data = build_task_data(fields, self.members_map, states, old)
        return self.plane_api.update_issue(project_id, task_id, data)

    @project_command
    async def update_task(self, update, context, project_id):
        fields = parse_task_message(update.effective_message.text)
        task = await asyncio.to_thread(self._update_task, project_id, fields)
        await update.effective_message.reply_text(
            "Task updated.\n" + self.plane_api.task_summary(project_id, task), parse_mode="HTML"
        )

    @project_command
    async def remove_task(self, update, context, project_id):
        parts = update.effective_message.text.split(maxsplit=1)
        value = parts[1].strip() if len(parts) == 2 else ""
        if value.startswith("UUID:"):
            value = value[5:].strip()
        task_id = validate_uuid(value, "Task UUID")
        await asyncio.to_thread(self.plane_api.remove_issue, project_id, task_id)
        await update.effective_message.reply_text("Task removed.")

    def _report(self, project_id, skip_empty=False):
        project = self.plane_api.get_project(project_id)
        tasks = self.plane_api.get_tasks_by_status_for_project(project_id)
        if skip_empty and not any(tasks.values()):
            return []
        return self.plane_api.generate_report_for_project(project_id, project, tasks)

    @project_command
    async def get_report(self, update, context, project_id):
        messages = await asyncio.to_thread(self._report, project_id)
        for message in messages:
            await update.effective_message.reply_text(message, parse_mode="HTML")

    async def send_report_to_chats(self):
        for project_id, chat_id in self.project_to_chat_map.items():
            try:
                messages = await asyncio.to_thread(self._report, project_id, True)
                for message in messages:
                    await self.application.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
            except (PlaneAPIError, ValueError) as error:
                logger.error("Report failed for project %s: %s", project_id, error)
            except TelegramError as error:
                logger.error(
                    "Report failed for project %s, chat %s: %s", project_id, chat_id, type(error).__name__
                )

    async def _start_scheduler(self, application):
        if not self.project_to_chat_map:
            logger.info("Setup mode: send /chatid to the bot in your target Telegram chat.")
            return
        if self.config.get("cron_expression") is None:
            logger.info("Bot started; scheduled reports are off (cron_expression: null).")
            return
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self.send_report_to_chats,
            CronTrigger.from_crontab(self.config["cron_expression"], timezone=self.config["cron_timezone"]),
            misfire_grace_time=60,
            coalesce=True,
            max_instances=1,
        )
        self.scheduler.start()
        logger.info("Bot started; scheduled reports enabled for %s projects.", len(self.project_to_chat_map))

    async def _stop_scheduler(self, application):
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def on_error(self, update, context):
        logger.error("Telegram handler failed: %s", type(context.error).__name__)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "The command failed. If it was a write command, check Plane before retrying."
                )
            except TelegramError:
                pass

    def run(self):
        self.application.run_polling(allowed_updates=["message"])
