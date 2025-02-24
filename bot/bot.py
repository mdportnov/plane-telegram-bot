import asyncio
import datetime
import logging
import re

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from croniter import croniter
from telegram import Bot, Update
from telegram.ext import CallbackContext, Application, CommandHandler

from bot.utils.utils import validate_dates, escape_markdown_v2, fail_emoji, index_to_priority, success_emoji
from bot.utils.utils_tg import get_mentions_list

class PlaneNotifierBot:
    def __init__(self, bot_token,bot_name, plane_api,config,members_map, projects_map):
        self.bot_token = bot_token
        self.bot_name = bot_name

        self.members_map = members_map
        self.project_to_chat_map = projects_map
        self.chat_to_project_map = {projects_map[item]: item for item in projects_map}

        self.plane_api = plane_api
        self.cron_expression = config["cron_expression"]
        self.cron_start_date = config["cron_start_date"]
        self.bot = Bot(token=self.bot_token)
        self.application = Application.builder().token(bot_token).build()
        self.stop_event = asyncio.Event()

        self.application.add_handler(CommandHandler('newtask', self.new_task))
        self.application.add_handler(CommandHandler('updatetask', self.update_task))
        self.application.add_handler(CommandHandler('getstates', self.get_states_list))
    async def send_report_to_chats(self):
        for project_id, chat_id in self.project_to_chat_map.items():
            logging.info(f"Processing project ID: {project_id} for chat ID: {chat_id}")

            # Fetch project details
            project_details = self.plane_api.get_project(project_id)
            if not project_details:
                logging.warning(f"No details found for project ID: {project_id}. Skipping.")
                continue

            # Fetch tasks categorized by status
            categorized_tasks = self.plane_api.get_tasks_by_status_for_project(project_id)
            if not categorized_tasks:
                logging.warning(f"No categorized tasks found for project ID: {project_id}. Skipping.")
                continue

            # Generate report for the project
            report = self.plane_api.generate_report_for_project(project_id, project_details, categorized_tasks)

            try:
                # Send report to the chat
                await self.bot.send_message(chat_id=chat_id, text=report, parse_mode="Markdown")
                logging.info(f"Successfully sent report for project ID: {project_id} to chat ID: {chat_id}.")
            except Exception as e:
                logging.error(f"Failed to send report to chat ID: {chat_id} for project ID: {project_id}. Error: {e}")

    async def get_states_list(self,update: Update,context : CallbackContext):
        try:
            command_text = update.message.text
            project_id = self.chat_to_project_map[str(update.message.chat_id)]
            states = self.plane_api.get_task_states_ids(project_id)

            self.plane_api.get_tasks_by_status_for_project(project_id)

            logging.info(f"states received :{states}")
            if states:
                await update.message.reply_text(
                    "\n".join(self.plane_api.map_states_by_ids(project_id).values())
                )
            else:
                await update.message.reply_text("An error occurred while getting states. Please try again later.")
        except Exception as e:
            logging.error(f"Error handling /getstates command: {e}, ${e.__cause__}")
            await update.message.reply_text(
                "An error occurred while getting states, try again later")
        return

    async def update_task(self,update: Update,context : CallbackContext):
        try:
            # Pattern for command
            update_issue_pattern = re.compile(
            rf'^/updatetask(?:@{self.bot_name})?[\s,]*' 
            r'\nUUID\s*:\s*(?P<id>\S{8}-\S{4}-\S{4}-\S{4}-\S{12})[\s,]*'
            r'(?:\nTitle\s*:\s*(?P<name>.+?)[\s,]*)?' 
            r'(?:\nDescription\s*:\s*(?P<description>.*?)[\s,]*)?' 
            r'(?:\nStart\s*:\s*(?P<start_date>\d{4}-\d{2}-\d{2})[\s,]*)?' 
            r'(?:\nDeadline\s*:\s*(?P<target_date>\d{4}-\d{2}-\d{2})[\s,]*)?' 
            r'(?:\nPriority\s*:\s*(?P<priority>[0-4])[\s,]*)?' 
            r'(?:\nState\s*:\s*(?P<state>.*?)[\s,]*)?'
            r'(?:@\w+[\s,]*)*$'
            ,re.MULTILINE)
            # Validate the command
            command_text = update.message.text
            match=update_issue_pattern.fullmatch(command_text)
            if not match :
                await update.message.reply_text(
                    fail_emoji +
                    "Invalid format. Use:\n"
                    "/updatetask\n"
                    "UUID: <task-UUID>\n"
                    "Title: <task-title>\n"
                    "Description: <task-description>\n"
                    "Start: <task-start-date> ( YYYY-MM-DD )\n"
                    "Deadline: <task-deadline-date> ( YYYY-MM-DD )\n"
                    "Priority: <(lowest)0->1->2->3->4(highest)>\n"
                    "State: <status-name>(check available with /getstates)\n"
                    "[ @assignees_names  ]"
                )
                return

            # Parse the command
            project_id = self.chat_to_project_map[str(update.message.chat_id)]
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
                replay = fail_emoji + f"Cant find assignees ids :"
                for name in invalid_names_list:
                    replay += f"\n @{name}"
                await update.message.reply_text(replay, parse_mode="MarkdownV2")
                return

            # Validate new_state and new_state_id
            if new_state is not None and new_state_id is None:
                await update.message.reply_text(fail_emoji + "New state not valid, check /getstates")
                return

             # Get old version of task
            old_issue = self.plane_api.get_task_by_uuid(project_id,task_id)
            logging.info(old_issue)
            if old_issue is None:
                await update.message.reply_text(fail_emoji + "Issue UUID invalid.Try again")
                return

            #Filter new assignees
            assignees_ids = [item for item in new_assignees_ids if item not in old_issue["assignees"]]
            # Validate dates
            if not validate_dates(new_start_date,new_target_date,old_issue) :
                await update.message.reply_text(fail_emoji + "Dates not valid.Try again")
                return

            # Prepare issue data
            new_issue_data = {
                "name": new_task_title ,
                "description_html": f"<body>{new_task_description}</body>" if new_task_description is not None else None,
                "start_date": new_start_date,
                "target_date": new_target_date,
                "priority": new_priority,
                "state":new_state_id,
                "assignees": assignees_ids
            }
            # Clean empty values
            for key,value in list(new_issue_data.items()) :
                if value is None:
                    new_issue_data.pop(key)
            # Update the issue via Plane API
            updated_issue = self.plane_api.update_issue(project_id,task_id,new_issue_data)
            if updated_issue:
                replay = self.construct_update_replay(updated_issue=updated_issue,old_issue=old_issue,project_id=project_id)
                await update.message.reply_text(replay,parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(fail_emoji + "Failed to update the task. Please try again later.")
        except Exception as e :
            logging.error(f"Error handling /updatetask command: {e}, ${e.__cause__}")
            await update.message.reply_text(
                fail_emoji + "An error occurred while updating the task. Please check your input and try again.")

    async def new_task(self, update: Update, context: CallbackContext):
        try:
            # Pattern for command
            new_issue_pattern =re.compile(
            rf'^/newtask(?:@{self.bot_name})?[\s,]*'
            r'\nTitle\s*:\s*(?P<name>.+?)[\s,]*'
            r'(?:\nDescription\s*:\s*(?P<description>.*?)[\s,]*)?'
            r'(?:\nStart\s*:\s*(?P<start_date>\d{4}-\d{2}-\d{2})[\s,]*)?'
            r'(?:\nDeadline\s*:\s*(?P<target_date>\d{4}-\d{2}-\d{2})[\s,]*)?'
            r'(?:\nPriority\s*:\s*(?P<priority>[0-4])[\s,]*)?'
            r'(?:\nState\s*:\s*(?P<state>.*?)[\s,]*)?'
            r'(?:@\w+[\s,]*)*$'
            ,re.MULTILINE)
            # Validate the command pattern
            command_text = update.message.text
            match=new_issue_pattern.fullmatch(command_text)
            if not match :
                await update.message.reply_text(
                    fail_emoji +
                    "Invalid format. Use:\n"
                    "/newtask\n"
                    "Title: <task-title>\n"
                    "Description(opt): <task-description>\n"
                    "Start(opt) : <task-start-date> ( YYYY-MM-DD )\n" 
                    "Deadline(opt) : <task-deadline-date> ( YYYY-MM-DD )\n"
                    "Priority(opt): <(lowest)0->1->2->3->4(highest)>\n"
                    "State(opt): <state-name>(check available with /getstates)\n"
                    "[ @assignees_names ]"
                )
                return
            # Parse the command
            project_id = self.chat_to_project_map[str(update.message.chat_id)]
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
                replay = fail_emoji + f"Cant find assignees ids :"
                for name in invalid_names_list:
                    replay +=f"\n @{name}"
                await update.message.reply_text(replay,parse_mode="MarkdownV2")
                return

            # Validate state and state_id
            if state is not None and state_id is None:
                await update.message.reply_text(fail_emoji + "State not valid ,check /getstates")
                return

            # Validate dates
            if not validate_dates(start_date,target_date) :
                await update.message.reply_text(fail_emoji + "Dates not valid.Try again")
                return

           # Prepare issue data
            issue_data = {
                "name": task_name,
                "description_html": f"<body>{task_description}</body>" if task_description is not None else None,
                "start_date": start_date,
                "target_date": target_date,
                "priority": priority,
                "state": state_id,
                "assignees" : assignees_ids
            }
            # Clean empty values
            for key,value in list(issue_data.items()) :
                if value is None:
                    issue_data.pop(key)
            # Create the issue via Plane API
            result = self.plane_api.create_issue(project_id, issue_data)
            if result:
                replay = self.construct_new_replay(result,project_id)
                await update.message.reply_text(replay,parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(fail_emoji + "Failed to create the task. Please try again later.")
        except Exception as e:
            logging.error(f"Error handling /newtask command: {e}, ${e.__cause__}")
            await update.message.reply_text(
                fail_emoji + "An error occurred while creating the task. Please check your input and try again.")


    async def run(self):
        logging.info("Starting PlaneNotifierBot...")
        try:
            scheduler = AsyncIOScheduler()
            mapped_cron = self.map_cron_expression(self.cron_expression,self.cron_start_date)
            print(mapped_cron)
            scheduler.add_job(
                self.periodic_task,
                CronTrigger(
                    minute = mapped_cron["minute"],
                    hour=mapped_cron["hour"],
                    day=mapped_cron["day_of_month"],
                    month=mapped_cron["month"],
                    day_of_week=mapped_cron["day_of_week"],
                    start_date= mapped_cron["start_date"]
                )
            )
            scheduler.start()

            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            await self.stop_event.wait()
        except KeyboardInterrupt:
            self.stop_event.set()
            logging.info("PlaneNotifierBot stopped by user.")
        finally:
            self.stop_event.set()
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            logging.info("PlaneNotifierBot stopped.")

    async def periodic_task(self):
        logging.info("Starting periodic report generation...")
        await self.send_report_to_chats()

    def map_cron_expression(self,cron_expression,cron_start_date):
        print(datetime.datetime.strptime(cron_start_date,"%Y-%m-%d %H:%M"))
        start_date = datetime.datetime.strptime(cron_start_date,"%Y-%m-%d %H:%M")
        cron = croniter(cron_expression)
        minute, hour, day_of_month, month, day_of_week  = cron.expanded
        print(cron.expanded)
        return {
            "minute" : ",".join(str(x) for x in minute),
            "hour" : ",".join(str(x) for x in hour),
            "day_of_month" : ",".join(str(x) for x in day_of_month),
            "month" : ",".join(str(x) for x in month),
            "day_of_week" : ",".join(str(x) for x in day_of_week),
            "start_date" : start_date
        }
    def construct_update_replay(self,updated_issue,old_issue,project_id):
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
            replay += f" \u2795 \@{md_v2(self.members_map.get(assignee_id))}\n"
        return replay
    def construct_new_replay(self, new_issue, project_id):
        md_v2 = escape_markdown_v2
        task_link = f"{self.plane_api.base_url}{self.plane_api.workspace_slug}/projects/{project_id}/issues/{new_issue['id']}"
        # Constructing replay
        replay = (
                success_emoji +
                f'Task created successfully:\n[{md_v2(new_issue["name"])}]({md_v2(task_link)})\n'
                f'ID: `{md_v2(new_issue["id"])}`\n'
                f'Title: {md_v2(new_issue["name"])}\n'
        )
        description_match = re.match(r'<.*?>(?P<description_text>.*?)</.*?>', new_issue['description_html'])
        if description_match:
            replay += f"Description: {description_match.group('description_text')}\n"
        if new_issue['start_date']:
            replay += f"Start: {new_issue['start_date']}\n"
        if new_issue['target_date']:
            replay += f"Deadline: {new_issue['target_date']}\n"
        if new_issue['priority'] != "none":
            replay += f"Priority:{new_issue['priority']}\n"
        states_map = self.plane_api.map_states_by_ids(project_id)
        if states_map.get(new_issue['state']):
            replay += f"State:{states_map.get(new_issue['state'])}\n"
        if new_issue["assignees"]:
            replay += f"Assignees:\n"
        for assignee_id in new_issue["assignees"]:
            replay += f"  {self.members_map.get(assignee_id)}\n"
        return replay
