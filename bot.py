import asyncio
import logging

from telegram import Bot, Update
from telegram.ext import CallbackContext, Updater, Application, CommandHandler


class PlaneNotifierBot:
    def __init__(self, bot_token, projects_map, plane_api, interval, members_map):
        self.bot_token = bot_token
        self.project_mapping = projects_map
        self.members_map = members_map
        self.plane_api = plane_api
        self.interval = interval
        self.bot = Bot(token=self.bot_token)
        self.application = Application.builder().token(bot_token).build()
        self.application.add_handler(CommandHandler('newtask', self.new_task))

    async def send_report_to_chats(self):
        for project_id, chat_id in self.project_mapping.items():
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
                print(f"Successfully sent report for project ID: {project_id} to chat ID: {chat_id}.")
            except Exception as e:
                print(f"Failed to send report to chat ID: {chat_id} for project ID: {project_id}. Error: {e}")

    async def new_task(self, update: Update, context: CallbackContext):
        try:
            # Parse the command arguments
            command_text = update.message.text
            if ',' not in command_text:
                await update.message.reply_text(
                    "Invalid format. Use: /newtask <project_id>, <task_name>, <description>, <start_date>, <target_date>, [<assignees>]")
                return

            # Split and clean arguments
            args = command_text.split(' ', 1)[1].split(',')
            args = [arg.strip().strip("'\"") for arg in args]

            # Validate minimum arguments
            if len(args) < 5:
                await update.message.reply_text(
                    "Invalid format. Use: /newtask <project_id>, <task_name>, <description>, <start_date>, <target_date>, [<assignees>]")
                return

            project_id = args[0]
            task_name = args[1]
            description = args[2]
            start_date = args[3] if args[3].lower() != 'null' else None
            target_date = args[4] if args[4].lower() != 'null' else None
            assignees = [assignee.strip() for assignee in args[5:]] if len(args) > 5 else []

            # Map assignees from Telegram IDs to Plane member IDs
            mapped_assignees = [
                member["member_id"]
                for member in self.plane_api.member_map
                if "telegram_id" in member and member["telegram_id"] in assignees
            ]

            # Debug log for parsed data
            print(
                f"Parsed Task: Project ID: {project_id}, Task Name: {task_name}, Description: {description}, Start Date: {start_date}, Target Date: {target_date}, Assignees: {assignees}")

            # Prepare issue data
            issue_data = {
                "name": task_name,
                "description_html": f"<body>{description}</body>",
                "start_date": start_date,
                "target_date": target_date,
                "assignees": mapped_assignees
            }

            # Create the issue via Plane API
            result = self.plane_api.create_issue(project_id, issue_data)
            if result:
                task_link = f"{self.plane_api.base_url}{self.plane_api.workspace_slug}/projects/{project_id}/issues/{result['id']}"
                await update.message.reply_text(f"Task created successfully: [{task_name}]({task_link})",
                                                parse_mode="Markdown")
            else:
                await update.message.reply_text("Failed to create the task. Please try again later.")
        except Exception as e:

            logging.error(f"Error handling /newtask command: {e}, ${e.__cause__}")
            await update.message.reply_text(
                "An error occurred while creating the task. Please check your input and try again.")

    def run(self):
        logging.info("Starting PlaneNotifierBot...")
        try:
            # asyncio.run(self.periodic_task())
            self.application.run_polling()
        except KeyboardInterrupt:
            logging.info("PlaneNotifierBot stopped by user.")

    async def periodic_task(self):
        while True:
            logging.info("Starting periodic report generation...")
            await self.send_report_to_chats()
            logging.info(f"Waiting for {self.interval} seconds until the next report...")
            await asyncio.sleep(self.interval)
