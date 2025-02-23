import asyncio
import os

import logging
from dotenv import load_dotenv

from bot.service.api import PlaneAPI
from bot.bot import PlaneNotifierBot
from bot.utils.utils import load_members_from_file, load_projects_from_file, load_config_from_file


async def main(runbot : PlaneNotifierBot ):
    await runbot.run()

if __name__ == '__main__':
    load_dotenv()
    workspace_slug = os.getenv('WORKSPACE_SLUG')
    api_token = os.getenv('API_TOKEN')
    base_url = os.getenv('BASE_URL')
    mode = os.getenv('MODE')
    bot_token = os.getenv('BOT_TOKEN')
    bot_name = os.getenv('BOT_NAME')
    members_file_path = "members.json"
    projects_file_path = "projects.json"
    config = load_config_from_file()

    members_map = load_members_from_file(members_file_path)
    projects_map = load_projects_from_file(projects_file_path)
    plane_api = PlaneAPI(api_token, workspace_slug,config, members_map, base_url, mode)
    bot = PlaneNotifierBot(bot_token, bot_name, plane_api,config, members_map, projects_map)

    projects_data = plane_api.get_all_projects()

    asyncio.run(bot.run())