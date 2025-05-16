import asyncio
import datetime
import re
import traceback
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from croniter import croniter
from telegram import Bot, Update
from telegram.ext import CallbackContext, Application, CommandHandler

from bot.service.api import PlaneAPI
from bot.utils.logger_config import setup_logger, logger
from bot.utils.utils import validate_dates, escape_markdown_v2, fail_emoji, index_to_priority, success_emoji
from bot.utils.utils_tg import get_mentions_list

class PlaneNotifierBot:
    def __init__(self, bot_token, bot_name, plane_api: PlaneAPI, config, members_map, projects_map):
        self.bot_token = bot_token
        self.bot_name = bot_name

        self.members_map = members_map
        self.project_to_chat_map = projects_map
        self.chat_to_project_map = {projects_map[item]: item for item in projects_map}

        self.plane_api = plane_api
        self.cron_expression = config["cron_expression"]
        self.timezone = config["cron_timezone"]

        self.bot = Bot(token=self.bot_token)
        self.application = Application.builder().token(bot_token).build()
        self.stop_event = asyncio.Event()

        self.application.add_handler(CommandHandler('newtask', self.new_task))
        self.application.add_handler(CommandHandler('updatetask', self.update_task))
        self.application.add_handler(CommandHandler('getstates', self.get_states_list))
        self.application.add_handler(CommandHandler('getreport', self.get_report))

    async def send_report_to_chats(self):
        for project_id, chat_id in self.project_to_chat_map.items():
            logger.info(f"Processing project UUID: {project_id} for chat UUID: {chat_id}")

            # Fetch project details
            project_details = self.plane_api.get_project(project_id)
            if not project_details:
                logger.warning(f"No details found for project UUID: {project_id}. Skipping")
                continue

            # Fetch tasks categorized by status
            categorized_tasks = self.plane_api.get_tasks_by_status_for_project(project_id)
            if not categorized_tasks:
                logger.warning(f"No categorized tasks found for project UUID: {project_id}. Skipping")
                continue
            if all((value is None or value == list()) for value in categorized_tasks.values()):
                logger.warning(f"No categorized tasks found for project UUID: {project_id}. Skipping")
                continue

            # Generate report for the project
            report = self.plane_api.generate_report_for_project(project_id, project_details, categorized_tasks)
            logger.debug(report)
            try:
                # Send report to the chat
                logger.info(f"Successfully sent report for project UUID: {project_id} to chat UUID: {chat_id}")
                await self.bot.send_message(chat_id=chat_id, text=report, parse_mode="MarkdownV2")
            except Exception as e:
                logger.error(f"Failed to send report to chat UUID: {chat_id} for project UUID: {project_id}. Error: {e}")
                error_reply = fail_emoji + escape_markdown_v2(" Failed to send report")
                if self.plane_api.mode.upper() == "DEBUG":
                    error_reply += escape_markdown_v2(f"\nError details : {e}")
                await self.bot.send_message(chat_id=chat_id, text=error_reply, parse_mode="MarkdownV2")

    async def get_states_list(self, update: Update, context: CallbackContext):
        try:
            project_id = self.chat_to_project_map[str(update.message.chat_id)]
            states = self.plane_api.get_task_states_ids(project_id)
            self.plane_api.get_tasks_by_status_for_project(project_id)
            logger.debug(f"states received :{states}")
            if states:
                await update.message.reply_text(
                    "\n".join(self.plane_api.map_states_by_ids(project_id).values())
                )
            else:
                await update.message.reply_text("An error occurred while getting states, try again")
        except Exception as e:
            logger.error(f"Error handling /getstates command: {e}, ${e.__cause__}")
            await update.message.reply_text(
                "An error occurred while getting states, try again")
        return

    async def update_task(self, update: Update, context: CallbackContext):
        try:
            # Pattern for command
            update_issue_pattern = re.compile(
                rf'^/updatetask(?:@{self.bot_name})?[\s,]*'
                r'\nUUID\s*:\s*(?P<id>\S{8}-\S{4}-\S{4}-\S{4}-\S{12})[\s,]*'
                r'(?:\nTitle\s*:\s*(?P<name>[^@]+?)[\s,]*)?'
                r'(?:\nDescription\s*:\s*(?P<description>[^@]*?)[\s,]*)?'
                r'(?:\nStart\s*:\s*(?P<start_date>\d{4}-\d{2}-\d{2})[\s,]*)?'
                r'(?:\nDeadline\s*:\s*(?P<target_date>\d{4}-\d{2}-\d{2})[\s,]*)?'
                r'(?:\nPriority\s*:\s*(?P<priority>[0-4])[\s,]*)?'
                r'(?:\nState\s*:\s*(?P<state>[^@]*?)[\s,]*)?'
                #r'(?:@[a-zA-Z0-9](?!.*?__)[a-zA-Z0-9_]{4,30}[a-zA-Z0-9][\s]*)*$'
                r'(?:(?<!\S)@[a-zA-Z0-9](?!.*?__)[a-zA-Z0-9_]{4,30}[a-zA-Z0-9](?!\s*\(https?://t\.me/(\S)*)(?:\s+|$))*$'
                , re.MULTILINE)

            # Validate the command
            command_text = update.message.text
            match = update_issue_pattern.fullmatch(command_text)
            if not match:
                await update.message.reply_text(
                    fail_emoji +
                    " Invalid format. Use:\n"
                    "/updatetask\n"
                    "UUID: <task-UUID>\n"
                    "Title: <task-title>\n"
                    "Description: <task-description>\n"
                    "Start: <task-start-date> (YYYY-MM-DD)\n"
                    "Deadline: <task-deadline-date> (YYYY-MM-DD)\n"
                    "Priority: <(lowest)0->1->2->3->4(highest)>\n"
                    "State: <state-name> (check with /getstates)\n"
                    "[@assignees_names]"
                )
                return

            # Parse the command
            project_id = self.chat_to_project_map.get(str(update.message.chat_id))
            if project_id is None:
                replay = fail_emoji + " Project with this chat_id is not specified in projects.json config"
                await update.message.reply_text(replay)
                return
            task_id = match.group("id")
            new_task_title = match.group("name")
            new_task_description = match.group("description")
            new_start_date = match.group("start_date")
            new_target_date = match.group("target_date")
            new_priority = index_to_priority.get(match.group("priority"))
            new_state = match.group("state")
            new_state_id = {v: k for k, v in self.plane_api.map_states_by_ids(project_id).items()}.get(new_state)
            new_assignees = get_mentions_list(update)
            inv_member_map = {v: k for k, v in self.members_map.items()}

            # Validate assignees
            new_assignees_ids = list()
            invalid_names_list = list()
            for assignee_name in new_assignees:
                if inv_member_map.get(assignee_name):
                    new_assignees_ids.append(inv_member_map.get(assignee_name))
                else:
                    invalid_names_list.append(assignee_name)
            if invalid_names_list and new_assignees:
                replay = fail_emoji + f" Can't find assignees ids:"
                for name in invalid_names_list:
                    replay += f"\n @{name}"
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
                return

            # Validate new_state and new_state_id
            if new_state is not None and new_state_id is None:
                await update.message.reply_text(fail_emoji + " Invalid new state, check /getstates and try again")
                return

            # Get old version of task
            old_issue = self.plane_api.get_task_by_uuid(project_id, task_id)
            if old_issue is None:
                await update.message.reply_text(fail_emoji + " Invalid issue UUID, try again")
                return

            # Filter new assignees
            assignees_ids = [item for item in new_assignees_ids if item not in old_issue["assignees"]]

            # Validate dates
            if not validate_dates(new_start_date, new_target_date, old_issue):
                await update.message.reply_text(fail_emoji + " Invalid dates, try again")
                return

            # Prepare issue data
            new_issue_data = {
                "name": new_task_title,
                "description_html": f"<body>{new_task_description}</body>" if new_task_description is not None else None,
                "start_date": new_start_date,
                "target_date": new_target_date,
                "priority": new_priority,
                "state": new_state_id,
                "assignees": assignees_ids
            }

            # Clean empty values
            for key, value in list(new_issue_data.items()):
                if value is None:
                    new_issue_data.pop(key)

            # Update the issue via Plane API
            updated_issue = self.plane_api.update_issue(project_id, task_id, new_issue_data)
            if updated_issue:
                replay = self.construct_update_replay(updated_issue=updated_issue, old_issue=old_issue,
                                                      project_id=project_id)
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
            else:
                error_reply = fail_emoji + " Failed to update the task, try again"
                if self.plane_api.mode.upper() == "DEBUG":
                    error_reply += f"\nApi response : ${updated_issue}"
                await update.message.reply_text(error_reply)
        except Exception as e:
            logger.error(f"Error handling /updatetask command: {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()}")
            error_reply = fail_emoji + " An error occurred while updating the task. Please check your input and try again"
            if self.plane_api.mode.upper() == "DEBUG":
                error_reply += f"\nError : {e} \n Error details :{traceback.format_exc()}"
            await update.message.reply_text(error_reply)

    async def new_task(self, update: Update, context: CallbackContext):
        try:
            # Pattern for command
            new_issue_pattern = re.compile(
                rf'^/newtask(?:@{self.bot_name})?[\s,]*'
                r'\nTitle\s*:\s*(?P<name>[^@]+?)[\s,]*'
                r'(?:\nDescription\s*:\s*(?P<description>[^@]*?)[\s,]*)?'
                r'(?:\nStart\s*:\s*(?P<start_date>\d{4}-\d{2}-\d{2})[\s,]*)?'
                r'(?:\nDeadline\s*:\s*(?P<target_date>\d{4}-\d{2}-\d{2})[\s,]*)?'
                r'(?:\nPriority\s*:\s*(?P<priority>[0-4])[\s,]*)?'
                r'(?:\nState\s*:\s*(?P<state>[^@]*?)[\s,]*)?'
                #r'(?:@[a-zA-Z0-9](?!.*?__)[a-zA-Z0-9_]{4,30}[a-zA-Z0-9][\s]*)*$'
                r'(?:(?<!\S)@[a-zA-Z0-9](?!.*?__)[a-zA-Z0-9_]{4,30}[a-zA-Z0-9](?!\s*\(https?://t\.me/(\S)*)(?:\s+|$))*$'
                , re.MULTILINE)

            # Validate the command pattern
            command_text = update.message.text
            match = new_issue_pattern.fullmatch(command_text)
            if not match:
                await update.message.reply_text(
                    fail_emoji +
                    " Invalid format. Use:\n"
                    "/newtask\n"
                    "Title: <task-title>\n"
                    "Description (optional): <task-description>\n"
                    "Start (optional): <task-start-date> (YYYY-MM-DD)\n"
                    "Deadline (optional): <task-deadline-date> (YYYY-MM-DD)\n"
                    "Priority (optional): <(lowest)0->1->2->3->4(highest)>\n"
                    "State (optional): <state-name> (check with /getstates)\n"
                    "[@assignees_names]"
                )
                return

            # Parse the command
            project_id = self.chat_to_project_map.get(str(update.message.chat_id))
            if project_id is None:
                replay = fail_emoji + " Project with this chat_id is not specified in projects.json config"
                await update.message.reply_text(replay)
                return
            task_name = match.group("name")
            task_description = match.group("description")
            start_date = match.group("start_date")
            target_date = match.group("target_date")
            priority = index_to_priority.get("priority")
            state = match.group("state")
            state_id = {v: k for k, v in self.plane_api.map_states_by_ids(project_id).items()}.get(state)
            assignees = get_mentions_list(update)
            inv_member_map = {v: k for k, v in self.members_map.items()}

            # Validate assignees
            assignees_ids = list()
            invalid_names_list = list()
            for assignee_name in assignees:
                if inv_member_map.get(assignee_name):
                    assignees_ids.append(inv_member_map.get(assignee_name))
                else:
                    invalid_names_list.append(assignee_name)
            if invalid_names_list and assignees:
                replay = fail_emoji + f" Can't find assignees ids :"
                for name in invalid_names_list:
                    replay += f"\n @{name}"
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
                return

            # Validate state and state_id
            if state is not None and state_id is None:
                await update.message.reply_text(fail_emoji + " Invalid state, check /getstates and try again")
                return

            # Validate dates
            if not validate_dates(start_date, target_date):
                await update.message.reply_text(fail_emoji + " Invalid dates, try again")
                return

            # Prepare issue data
            issue_data = {
                "name": task_name,
                "description_html": f"<body>{task_description}</body>" if task_description is not None else None,
                "start_date": start_date,
                "target_date": target_date,
                "priority": priority,
                "state": state_id,
                "assignees": assignees_ids
            }

            # Clean empty values
            for key, value in list(issue_data.items()):
                if value is None:
                    issue_data.pop(key)

            # Create the issue via Plane API
            result = self.plane_api.create_issue(project_id, issue_data)
            if result:
                replay = self.construct_new_replay(result, project_id)
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
            else:
                error_reply = fail_emoji + " Failed to create the task, try again"
                if self.plane_api.mode.upper() == "DEBUG":
                    error_reply += f"\nApi response : ${result}"
                await update.message.reply_text(error_reply)
        except Exception as e:
            logger.error(f"Error handling /newtask command: {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()} ")
            error_reply = fail_emoji + " An error occurred while creating the task, check your input and try again"
            if self.plane_api.mode.upper() == "DEBUG":
                error_reply += f"\nError : {e} \n Error details :{traceback.format_exc()}"
            await update.message.reply_text(error_reply)

    async def get_report(self, update: Update, context: CallbackContext):
        """Handles the /getreport command"""
        message = update.message
        chat_id = message.chat_id

        try:
            # 1. Retrieve Project ID from mapping
            project_id = self.chat_to_project_map.get(str(update.message.chat_id))
            if project_id is None:
                replay = fail_emoji + "Project with this chat_id is not specified in JSON config"
                await update.message.reply_text(replay)
                return

            # 2. Fetch Project Details and Tasks
            project_details = self.plane_api.get_project(project_id)
            if not project_details:
                await update.message.reply_text(f"No details found for project UUID: {project_id}")
                return

            categorized_tasks = self.plane_api.get_tasks_by_status_for_project(project_id)
            if not categorized_tasks:
                await update.message.reply_text(f"No tasks found for project UUID: {project_id}")
                return

            # 3. Generate Report
            report = self.plane_api.generate_report_for_project(project_id, project_details, categorized_tasks)

            # 4. Send Report
            try:
                await self.bot.send_message(chat_id=chat_id, text=report, parse_mode="MarkdownV2")
                logger.info(f"Successfully sent report for project UUID: {project_id} to chat UUID: {chat_id}")

            except Exception as e:
                error_reply = fail_emoji + " Failed to send report"
                if self.plane_api.mode.upper() == "DEBUG":
                    error_reply += f"\nError : {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()}"
                logger.error(f"Failed to send report to chat UUID: {chat_id} for project UUID: {project_id}. Error: {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()}")
                await update.message.reply_text(error_reply)

        except Exception as e:
            error_reply = fail_emoji + "An unexpected error occurred "
            if self.plane_api.mode.upper() == "DEBUG":
                error_reply += f"\nError : {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()}"
            logger.error(f"Error processing /getreport command for chat UUID: {chat_id}. Error: {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()}")
            await update.message.reply_text(error_reply)  # Generic error message

    async def run(self):
        logger.info("Starting PlaneNotifierBot...")
        try:
            scheduler = AsyncIOScheduler()
            cronTrigger = CronTrigger.from_crontab(
                self.cron_expression,
                timezone=self.timezone
            )
            scheduler.add_job(
                func=self.send_report_to_chats,
                trigger=cronTrigger,
                misfire_grace_time=30
            )
            scheduler.start()

            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            await self.stop_event.wait()
        except KeyboardInterrupt:
            self.stop_event.set()
            logger.info("PlaneNotifierBot stopped by user")
        finally:
            self.stop_event.set()
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            logger.info("PlaneNotifierBot stopped")

    async def periodic_task(self):
        logger.info("Starting periodic report generation...")
        await self.send_report_to_chats()

    def map_cron_expression(self, cron_expression, cron_start_date, timezone):
        start_date = datetime.datetime.strptime(cron_start_date, "%Y-%m-%d %H:%M")
        cron = croniter(cron_expression)
        minute, hour, day_of_month, month, day_of_week = cron.expanded
        return {
            "minute": ",".join(str(x) for x in minute),
            "hour": ",".join(str(x) for x in hour),
            "day_of_month": ",".join(str(x) for x in day_of_month),
            "month": ",".join(str(x) for x in month),
            "day_of_week": ",".join(str(x) for x in day_of_week),
            "start_date": start_date,
            "timezone": timezone
        }

    def construct_update_replay(self, updated_issue, old_issue, project_id):
        md_v2 = escape_markdown_v2
        task_link = f"{self.plane_api.base_url}{self.plane_api.workspace_slug}/projects/{project_id}/issues/{updated_issue['id']}"
        replay = (
                success_emoji +
                f"Task updated successfully:\n[{md_v2(updated_issue['name'])}]({md_v2(task_link)})\n"
                f"UUID:`{md_v2(updated_issue['id'])}`\n"
        )
        if old_issue['name'] != updated_issue['name']:
            replay += f"Title: ~{md_v2(old_issue['name'])}~ \u21D2 {md_v2(updated_issue['name'])}\n"

        old_description_match = re.fullmatch(r'<.*?>(?P<description>.*?)</.*?>', old_issue['description_html'])
        updated_description_match = re.fullmatch(r'<.*?>(?P<description>.*?)</.*?>', updated_issue['description_html'])
        if (
                old_description_match is not None and updated_description_match is not None
                and
                old_description_match.group("description") != updated_description_match.group("description")
        ):
            replay += (
                f"Description: "
                f"~{md_v2(old_description_match.group('description')) if old_description_match.group('description') else None}~"
                f" \u21D2 "
                f"{md_v2(updated_description_match.group('description'))}\n"
            )
        if old_issue['start_date'] != updated_issue['start_date']:
            replay += f"Start: ~{md_v2(old_issue['start_date'])}~ \u21D2 {md_v2(updated_issue['start_date'])}\n"
        if old_issue['target_date'] != updated_issue['target_date']:
            replay += f"Deadline : ~{md_v2(old_issue['target_date'])}~ \u21D2 {md_v2(updated_issue['target_date'])}\n"
        if old_issue['priority'] != updated_issue['priority']:
            replay += f"Priority: ~{md_v2(old_issue['priority'])}~ \u21D2 {md_v2(updated_issue['priority'])}\n"
        states_map = self.plane_api.map_states_by_ids(project_id)
        if states_map.get(old_issue['state']) != states_map.get(updated_issue['state']):
            replay += (
                f"State: ~{md_v2(states_map.get(old_issue['state']))}~"
                f" \u21D2 "
                f"{md_v2(states_map.get(updated_issue['state']))}\n"
            )
        if updated_issue["assignees"] != old_issue["assignees"]:
            replay += f"Assignees:\n"
        for assignee_id in [item for item in updated_issue["assignees"] if item not in old_issue["assignees"]]:
            replay += f" \u2795 @{md_v2(self.members_map.get(assignee_id))}\n"
        return replay

    def construct_new_replay(self, new_issue, project_id):
        md_v2 = escape_markdown_v2
        task_link = f"{self.plane_api.base_url}{self.plane_api.workspace_slug}/projects/{project_id}/issues/{new_issue['id']}"

        # Constructing replay
        replay = (
                success_emoji +
                f'Task created successfully:\n[{md_v2(new_issue["name"])}]({md_v2(task_link)})\n'
                f'UUID: `{md_v2(new_issue["id"])}`\n'
                f'Title: {md_v2(new_issue["name"])}\n'
        )

        description_match = re.match(r'<.*?>(?P<description_text>.*?)</.*?>', new_issue['description_html'])
        if description_match:
            replay += f"Description: {md_v2(description_match.group('description_text'))}\n"
        if new_issue['start_date']:
            replay += f"Start: {md_v2(new_issue['start_date'])}\n"
        if new_issue['target_date']:
            replay += f"Deadline: {md_v2(new_issue['target_date'])}\n"
        if new_issue['priority'] != "none":
            replay += f"Priority: {md_v2(new_issue['priority'])}\n"
        states_map = self.plane_api.map_states_by_ids(project_id)
        if states_map.get(new_issue['state']):
            replay += f"State: {md_v2(states_map.get(new_issue['state']))}\n"
        if new_issue["assignees"]:
            replay += f"Assignees:\n"
        for assignee_id in new_issue["assignees"]:
            replay += f" @{md_v2(self.members_map.get(assignee_id))}\n"
        return replay
