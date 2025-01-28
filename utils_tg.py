import json
import logging

import requests


def get_all_chats(token):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    response = requests.get(url)
    if response.status_code == 200:
        updates = response.json()
        logging.log(logging.INFO,
                    f"Received response from Telegram API: {json.dumps(updates, indent=4, ensure_ascii=False)}")
        chats = {}
        for update in updates.get("result", []):
            if "message" in update:
                chat = update["message"]["chat"]
                chats[chat["id"]] = chat.get("title", chat.get("username", "Private Chat"))
        return chats
    else:
        print(f"Failed to fetch updates: {response.text}")
        return None
