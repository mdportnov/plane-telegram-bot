from telegram import Bot
from telegram.ext import Updater


class PlaneNotifierBot:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.bot = Bot(token=self.bot_token)
        self.updater = Updater(token=self.bot_token, use_context=True)
        self.dispatcher = self.updater.dispatcher

    project_chat_mapping = {
        'project_id_1': 'chat_id_1',
        'project_id_2': 'chat_id_2',
    }
