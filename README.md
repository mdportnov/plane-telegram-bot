# PlaneAPI Telegram Bot Integration

This project provides a Python-based integration for managing and reporting tasks from Plane.so projects. The bot
interacts with the Plane.so API to fetch project details, task statuses, and generates task reports tailored for
Telegram.

### Features

- Retrieve all projects in a workspace.
- Fetch tasks for specific projects categorized by statuses (Todo, In Progress, In Review).
- Generate Telegram-ready reports with clickable links to tasks and user profiles.

### Requirements

- Python 3.13
- requests library for API calls
- Plane.so API key

### Known issues:

1. https://github.com/makeplane/plane/issues/5061 - that's why members.json should be used for mapping
2. in Create Issue API - not working creating assignees

### Setup

1. Create `.env` file in root folder, specify variables:
    - API_TOKEN – token generated in your plane.so profile
    - BASE_URL - url for your plane.so server
    - WORKSPACE_SLUG - workspace sub-path in url
    - BOT_TOKEN - telegram bot api token
    - MODE - set `debug` for logging
2. Create file mappers (unfortunately plane.so API can't provide all necessary info in appropriate way) in the next
   structure:
    - members.json
       ```json
       [
         {
           "project_id": "af0d57f1-107e-455a4-91a1-7c15022c16e1",
           "chat_id": "-3753448353"
         },
         {
         }
       ]
       ```
    - projects.json
       ```json
       [
         {
           "member_id": "55c56d6c-13f6-4dd1-be67-a39992eff736",
           "member__display_name": "nickname_from_plane",
           "telegram_id": "@nickname_from_telegram"
         },
         {
         }
       ]
       ```

3. Run `pip install -r requirements.txt`
4. Use PyCharm Run Configuration or just `python main.py`
