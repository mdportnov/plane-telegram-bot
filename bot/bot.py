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
from bot.utils.utils import validate_dates, escape_markdown_v2, fail_emoji, index_to_priority, success_emoji, \
    html_to_markdownV2, normalize_date
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
        self.application.add_handler(CommandHandler('removetask', self.remove_task))
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

    async def new_task(self, update: Update, context: CallbackContext):
        try:
            md_v2 = escape_markdown_v2
            # Validate the command pattern
            command_text = update.message.text
            new_task_pattern = re.compile(rf'^/newtask(?:@{self.bot_name})?[\s,]*')
            match = new_task_pattern.match(command_text)
            fail_replay = ( fail_emoji +
                      " Invalid format. Use:\n"
                      "/newtask\n"
                      "Title: <task-title> (max length = 255)\n"
                      "Description: <task-description>\n"
                      "Start: <task-start-date> (YYYY-MM-DD)\n"
                      "Deadline: <task-deadline-date> (YYYY-MM-DD)\n"
                      "Priority: <(lowest)0->1->2->3->4(highest)>\n"
                      "State: <state-name> (check with /getstates)\n"
                      "@assignees_names"
                      )
            if match is None :
                await update.message.reply_text(md_v2(fail_replay), parse_mode="MarkdownV2")
                return
            # Parse the command
            project_id = self.chat_to_project_map.get(str(update.message.chat_id))
            if project_id is None:
                replay = fail_emoji + " Project with this chat_id is not specified in projects.json config"
                await update.message.reply_text(md_v2(replay), parse_mode="MarkdownV2")
                return
            test_parse_task = self.parse_newtask_message(message=update.message.text)

            task_name : str = test_parse_task.get("title")
            task_description = test_parse_task.get("description")
            start_date = test_parse_task.get("start")
            target_date = test_parse_task.get("deadline")
            priority_id = test_parse_task.get("priority")
            state = test_parse_task.get("state")

            #Validate title
            if task_name is None or task_name == "" :
                await update.message.reply_text(md_v2(fail_replay), parse_mode="MarkdownV2")
                return
            if len(task_name) >=255 :
                await update.message.reply_text(md_v2(fail_emoji + f"Max title length is 255 symbols,your title length is {len(task_name)}"), parse_mode="MarkdownV2")
                return
             # Validate priority
            priority = index_to_priority.get(priority_id)
            if priority is None and priority_id is not None :
                await update.message.reply_text(md_v2((fail_emoji + " Invalid priority, use one from range : (lowest)0->1->2->3->4(highest)")), parse_mode="MarkdownV2")
                return

            # Validate state and state_id
            state_id = {v: k for k, v in self.plane_api.map_states_by_ids(project_id).items()}.get(state)
            if state is not None and state_id is None:
                await update.message.reply_text(md_v2(fail_emoji + " Invalid state, check /getstates and try again"), parse_mode="MarkdownV2")
                return

            # Validate dates
            start_date_fixed = normalize_date(start_date)
            target_date_fixed = normalize_date(target_date)
            if (not start_date_fixed and start_date) or (not target_date_fixed and target_date):
                await update.message.reply_text(md_v2(fail_emoji + " Invalid dates, try again"), parse_mode="MarkdownV2")
                return
            if not validate_dates(start_date_fixed, target_date_fixed):
                await update.message.reply_text(md_v2(fail_emoji + " Invalid dates, try again"), parse_mode="MarkdownV2")
                return
            start_date = start_date_fixed
            target_date = target_date_fixed
            # Validate assignees
            assignees = get_mentions_list(update)
            inv_member_map = {v: k for k, v in self.members_map.items()}
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
                await update.message.reply_text(md_v2(replay), parse_mode="MarkdownV2")
                return

            # Prepare issue data
            task_data = {
                "name": task_name,
                "description_html": f"<body>{task_description}</body>" if task_description is not None else None,
                "start_date": start_date,
                "target_date": target_date,
                "priority": priority_id,
                "state": state_id,
                "assignees": assignees_ids
            }

            # Clean empty values
            for key, value in list(task_data.items()):
                if value is None:
                    task_data.pop(key)

            # Create the issue via Plane API
            success , result = self.plane_api.create_issue(project_id, task_data)
            if success:
                replay = self.construct_new_replay(new_task=result, project_id=project_id)
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
            else:
                error_reply = fail_emoji + " Failed to create the task, try again"
                if self.plane_api.mode.upper() == "DEBUG":
                    error_reply += f"\nDetails : ${result}"
                await update.message.reply_text(md_v2(error_reply), parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Error handling /newtask command: {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()} ")
            error_reply = fail_emoji + " An error occurred while creating the task, check your input and try again"
            if self.plane_api.mode.upper() == "DEBUG":
                error_reply += f"\nError : {e} \n Error details :{traceback.format_exc()}"
            await update.message.reply_text(escape_markdown_v2(error_reply), parse_mode="MarkdownV2")

    async def update_task(self, update: Update, context: CallbackContext):
        try:
            md_v2 = escape_markdown_v2
            # Validate the command
            command_text = update.message.text
            update_task_pattern = re.compile(re.compile(rf'^/updatetask(?:@{self.bot_name})?[\s,]*'
                r'\nUUID\s*:?\s*(?P<id>\S{8}-\S{4}-\S{4}-\S{4}-\S{12})[\s,]*'))

            match = update_task_pattern.match(command_text)
            fail_replay = ( fail_emoji +
                    " Invalid format. Use:\n"
                    "/updatetask\n"
                    "UUID: <task-UUID> (max length = 255)\n"
                    "Title: <task-title>\n"
                    "Description: <task-description>\n"
                    "Start: <task-start-date> (YYYY-MM-DD)\n"
                    "Deadline: <task-deadline-date> (YYYY-MM-DD)\n"
                    "Priority: <(lowest)0->1->2->3->4(highest)>\n"
                    "State: <state-name> (check with /getstates)\n"
                    "@assignees_names"
                    )
            if match is None:
                await update.message.reply_text(md_v2(fail_replay), parse_mode="MarkdownV2")
                return
            # Parse the command
            project_id = self.chat_to_project_map.get(str(update.message.chat_id))
            if project_id is None:
                replay = fail_emoji + " Project with this chat_id is not specified in projects.json config"
                await update.message.reply_text(md_v2(replay), parse_mode="MarkdownV2")
                return
            new_parse_task = self.parse_updatetask_message(message=update.message.text)
            task_id = new_parse_task.get("id")
            new_task_title = new_parse_task.get("title")
            new_task_description = new_parse_task.get("description")
            new_start_date = new_parse_task.get("start")
            new_target_date = new_parse_task.get("deadline")
            new_priority_id = new_parse_task.get("priority")
            new_state = new_parse_task.get("state")

            uuid_pattern = re.compile(r'\s*(\S{8}-\S{4}-\S{4}-\S{4}-\S{12})[\s,]*')
            if task_id is None or uuid_pattern.fullmatch(task_id) is None :
                replay = fail_emoji + " Task id's incorrect"
                await update.message.reply_text(md_v2(replay), parse_mode="MarkdownV2")
                return
            if new_task_title == "":
                replay = fail_emoji + " Task title cant be empty"
                await update.message.reply_text(md_v2(replay), parse_mode="MarkdownV2")
                return
            if new_task_title is not None and len(new_task_title) >=255 :
                await update.message.reply_text(md_v2(fail_emoji + f"Max title length is 255 symbols,your title length is {len(new_task_title)}"), parse_mode="MarkdownV2")
                return
            # Validate priority
            new_priority = index_to_priority.get(new_priority_id)
            if new_priority is None and new_priority_id is not None :
                await update.message.reply_text(md_v2(fail_emoji + " Invalid priority, use one from range : (lowest)0->1->2->3->4(highest)"), parse_mode="MarkdownV2")
                return
            # Validate state and state_id
            new_state_id = {v: k for k, v in self.plane_api.map_states_by_ids(project_id).items()}.get(new_state)
            if new_state is not None and new_state_id is None:
                await update.message.reply_text(md_v2(fail_emoji + " Invalid state, check /getstates and try again"), parse_mode="MarkdownV2")
                return
            # Validate dates
            start_date_fixed = normalize_date(new_start_date)
            target_date_fixed = normalize_date(new_target_date)
            if (not start_date_fixed and new_start_date) or (not target_date_fixed and new_target_date):
                await update.message.reply_text(md_v2(fail_emoji + " Invalid dates, try again"), parse_mode="MarkdownV2")
                return
            if not validate_dates(start_date_fixed, target_date_fixed):
                await update.message.reply_text(md_v2(fail_emoji + " Invalid dates, try again"), parse_mode="MarkdownV2")
                return
            new_start_date = start_date_fixed
            new_target_date = target_date_fixed
            # Validate assignees
            new_assignees = get_mentions_list(update)
            inv_member_map = {v: k for k, v in self.members_map.items()}
            new_assignees_ids = list()
            invalid_names_list = list()
            for assignee_name in new_assignees:
                if inv_member_map.get(assignee_name):
                    new_assignees_ids.append(inv_member_map.get(assignee_name))
                else:
                    invalid_names_list.append(assignee_name)
            if invalid_names_list and new_assignees:
                replay = fail_emoji + f" Can't find assignees ids :"
                for name in invalid_names_list:
                    replay += f"\n @{name}"
                await update.message.reply_text(md_v2(replay), parse_mode="MarkdownV2")
                return

            # Get old version of task
            old_task = self.plane_api.get_task_by_uuid(project_id, task_id)
            if old_task is None:
                await update.message.reply_text(md_v2(fail_emoji + " Invalid issue UUID, try again"), parse_mode="MarkdownV2")
                return

            # Filter new assignees
            assignees_ids = list(set(new_assignees_ids + old_task.get("assignees")))
            # Validate dates
            if not validate_dates(new_start_date, new_target_date, old_task):
                await update.message.reply_text(md_v2(fail_emoji + " Invalid dates, try again"), parse_mode="MarkdownV2")
                return

            # Prepare issue data
            new_task_data = {
                "name": new_task_title,
                "description_html": f"<body>{new_task_description}</body>" if new_task_description is not None else None,
                "start_date": new_start_date,
                "target_date": new_target_date,
                "priority": new_priority,
                "state": new_state_id,
                "assignees": assignees_ids
            }

            # Clean empty values
            for key, value in list(new_task_data.items()):
                if value is None:
                    new_task_data.pop(key)

            # Update the issue via Plane API
            success,result = self.plane_api.update_issue(project_id, task_id, new_task_data)
            if success:
                replay = self.construct_update_replay(updated_task=result, old_task=old_task, project_id=project_id)
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
            else:
                error_reply = fail_emoji + " Failed to update the task, try again"
                if self.plane_api.mode.upper() == "DEBUG":
                    error_reply += f"\nDetails: ${result}"
                await update.message.reply_text(md_v2(error_reply), parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Error handling /updatetask command: {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()}")
            error_reply = fail_emoji + " An error occurred while updating the task. Please check your input and try again"
            if self.plane_api.mode.upper() == "DEBUG":
                error_reply += f"\nError : {e} \n Error details :{traceback.format_exc()}"
            await update.message.reply_text(escape_markdown_v2(error_reply), parse_mode="MarkdownV2")

    async def remove_task(self, update: Update, context: CallbackContext):
        try:
            # Pattern for command
            remove_task_pattern = re.compile(
                rf'^/removetask(?:@{self.bot_name})?[\s,]*'
                r'(\nUUID\s*:)?\s*(?P<id>\S{8}-\S{4}-\S{4}-\S{4}-\S{12})[\s,]*'
                , re.MULTILINE)

            # Validate the command pattern
            command_text = update.message.text
            match = remove_task_pattern.fullmatch(command_text)
            if not match:
                await update.message.reply_text(
                    fail_emoji +
                    " Invalid format. Use:\n"
                    "/removetask <task-uuid>\n"
                )
                return

            # Parse the command
            project_id = self.chat_to_project_map.get(str(update.message.chat_id))
            if project_id is None:
                replay = fail_emoji + " Project with this chat_id is not specified in projects.json config"
                await update.message.reply_text(replay)
                return
            task_id = match.group("id")
            # Check if issue exist
            issue_to_delete = self.plane_api.get_task_by_uuid(project_id, task_id)
            if issue_to_delete is None :
                replay = fail_emoji + " Task with provided uuid doesnt exist"
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
                return
            # Delete the issue via Plane API
            success , result = self.plane_api.remove_issue(project_id, task_id)
            if success :
                replay = success_emoji + " Task removed successfully"
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
            else:
                error_reply = fail_emoji + " Failed to remove task, try again"
                if self.plane_api.mode.upper() == "DEBUG":
                    error_reply += f"\nDetails : ${result}"
                await update.message.reply_text(error_reply)
        except Exception as e:
            logger.error(f"Error handling /removetask command: {e} \nCause : {e.__cause__} \n Traceback:{traceback.format_exc()} ")
            error_reply = fail_emoji + " An error occurred while removing the task, check your input and try again"
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
                replay = fail_emoji + " Project with this chat_id is not specified in projects.json config"
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
            error_reply = fail_emoji + " An unexpected error occurred "
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

    def construct_update_replay(self, updated_task, old_task, project_id):
        md_v2 = escape_markdown_v2
        task_link = f"{self.plane_api.base_url}{self.plane_api.workspace_slug}/projects/{project_id}/issues/{updated_task['id']}"
        replay = (
                success_emoji +
                f" Task updated successfully:\n[{md_v2(updated_task['name'])}]({md_v2(task_link)})\n"
                f"UUID: `{md_v2(updated_task['id'])}`\n"
        )
        if old_task['name'] != updated_task['name']:
            replay += f"Title: ~{md_v2(old_task['name'])}~ \u21D2 {md_v2(updated_task['name'])}\n"

        old_description_text= html_to_markdownV2(old_task.get("description_html"))
        updated_description_text = html_to_markdownV2(updated_task.get("description_html"))
        if (
                old_description_text != ""
                and
                old_description_text != updated_description_text
        ):
            replay += (
                f"Description: "
                f"~{old_description_text  if old_description_text else None}~"
                f" \u21D2 "
                f"{updated_description_text}\n"
            )
        if old_description_text == "" and updated_description_text != "" :
            replay += (
                f"Description: {updated_description_text}\n"
            )
        if old_task['start_date'] is not None and old_task['start_date'] != updated_task['start_date']:
            replay += f"Start: ~{md_v2(old_task['start_date'])}~ \u21D2 {md_v2(updated_task['start_date'])}\n"
        if old_task['start_date'] is None and updated_task['start_date'] is not None:
            replay += f"Start: {md_v2(updated_task['start_date'])}\n"
        if old_task['target_date'] is not None and old_task['target_date'] != updated_task['target_date']:
            replay += f"Deadline : ~{md_v2(old_task['target_date'])}~ \u21D2 {md_v2(updated_task['target_date'])}\n"
        if old_task['target_date'] is None and old_task['target_date'] != updated_task['target_date']:
            replay += f"Deadline : {md_v2(updated_task['target_date'])}\n"
        if old_task['priority'] == "none" and old_task['priority'] != updated_task['priority']:
            replay += f"Priority: {md_v2(updated_task['priority'])}\n"
        if old_task['priority'] != "none" and old_task['priority'] != updated_task['priority']:
            replay += f"Priority: ~{md_v2(old_task['priority'])}~ \u21D2 {md_v2(updated_task['priority'])}\n"
        states_map = self.plane_api.map_states_by_ids(project_id)
        if states_map.get(old_task['state']) != states_map.get(updated_task['state']):
            replay += (
                f"State: ~{md_v2(states_map.get(old_task['state']))}~"
                f" \u21D2 "
                f"{md_v2(states_map.get(updated_task['state']))}\n"
            )
        if updated_task["assignees"] != old_task["assignees"]:
            replay += f"Assignees:\n"
        for assignee_id in [item for item in updated_task["assignees"] if item not in old_task["assignees"]]:
            replay += f" \u2795 @{md_v2(self.members_map.get(assignee_id))}\n"
        return replay

    def construct_new_replay(self, new_task, project_id):
        md_v2 = escape_markdown_v2
        task_link = f"{self.plane_api.base_url}{self.plane_api.workspace_slug}/projects/{project_id}/issues/{new_task['id']}"

        # Constructing replay
        replay = (
                success_emoji +
                f' Task created successfully:\n[{md_v2(new_task.get("name"))}]({md_v2(task_link)})\n'
                f'UUID: `{md_v2(new_task.get("id"))}`\n'
                f'Title: {md_v2(new_task.get("name"))}\n'
        )

        description_text = html_to_markdownV2(new_task.get("description_html"))
        if description_text is not None and description_text != "":
            replay += f"Description: {description_text}\n"
        if new_task['start_date']:
            replay += f"Start: {md_v2(new_task.get('start_date'))}\n"
        if new_task['target_date']:
            replay += f"Deadline: {md_v2(new_task.get('target_date'))}\n"
        if new_task['priority'] != "none":
            replay += f"Priority: {md_v2(new_task.get('priority'))}\n"
        states_map = self.plane_api.map_states_by_ids(project_id)
        if states_map.get(new_task.get('state')):
            replay += f"State: {md_v2(states_map.get(new_task.get('state')))}\n"
        if new_task["assignees"]:
            replay += f"Assignees:\n"
        for assignee_id in new_task.get("assignees"):
            replay += f" @{md_v2(self.members_map.get(assignee_id))}\n"
        return replay

    def parse_newtask_message(self, message):
        patterns = {
            'title': re.compile(r'Title\s*:\s*(.*?)[\s,]*(?=\s*(?:Description[\s,]*:|Start[\s,]*:|Deadline[\s,]*:|Priority[\s,]*:|State[\s,]*:|@|\Z))', re.DOTALL),
            'description': re.compile(r'Description\s*:\s*(.*?)[\s,]*(?=\s*(?:Start[\s,]*:|Deadline[\s,]*:|Priority[\s,]*:|State[\s,]*:|@|\Z))', re.DOTALL),
            'start': re.compile(r'Start\s*:\s*(\S*)[\s,]*'),
            'deadline': re.compile(r'Deadline\s*:\s*(\S*)[\s,]*'),
            'priority': re.compile(r'Priority\s*:\s*(.*?)[\s,]*'),
            'state': re.compile(r'State\s*:\s*(.*?)(?=\n|$|@)[\s,]*'),
            'assignees': re.compile(r'(?:^|\s)(@\w+)')
        }

        parsed_data = {}

        for field, pattern in patterns.items():
            match = pattern.search(message)
            if match:
                if field in ['title', 'description', 'state']:
                    parsed_data[field] = match.group(1).strip()
                elif field == 'assignees':
                    matches = pattern.findall(message)
                    if matches:
                        parsed_data[field] = list(set(
                            name.strip().rstrip(',.!')  # Чистим ник от мусора
                            for name in matches
                        ))
                else:
                    parsed_data[field] = match.group(1).strip()

        # Валидация данных

        return parsed_data

    def parse_updatetask_message(self, message):
        patterns = {
            'id' : re.compile(r'\s*UUID\s*:\s*(\S*)[\s,]*'),
            'title': re.compile(r'Title\s*:\s*(.*?)[\s,]*(?=\s*(?:Description[\s,]*:|Start[\s,]*:|Deadline[\s,]*:|Priority[\s,]*:|State[\s,]*:|@|\Z))', re.DOTALL),
            'description': re.compile(r'Description\s*:\s*(.*?)[\s,]*(?=\s*(?:Start[\s,]*:|Deadline[\s,]*:|Priority[\s,]*:|State[\s,]*:|@|\Z))', re.DOTALL),
            'start': re.compile(r'Start\s*:\s*(\S*)[\s,]*'),
            'deadline': re.compile(r'Deadline\s*:\s*(\S*)[\s,]*'),
            'priority': re.compile(r'Priority\s*:\s*(.*?)[\s,]*'),
            'state': re.compile(r'State\s*:\s*(.*?)(?=\n|$|@)[\s,]*'),
            'assignees': re.compile(r'(?:^|\s)(@\w+)')
        }

        parsed_data = {}

        for field, pattern in patterns.items():
            match = pattern.search(message)
            if match:
                if field in ['title', 'description', 'state']:
                    parsed_data[field] = match.group(1).strip()
                elif field == 'assignees':
                    matches = pattern.findall(message)
                    if matches:
                        parsed_data[field] = list(set(
                            name.strip().rstrip(',.!')  # Чистим ник от мусора
                            for name in matches
                        ))
                else:
                    parsed_data[field] = match.group(1).strip()

        # Валидация данных

        return parsed_data