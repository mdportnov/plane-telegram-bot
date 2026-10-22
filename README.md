# Plane Telegram Bot

Create, update and delete Plane work items from Telegram, and send scheduled project reports to your team chat. Works with Plane Cloud and self-hosted Plane. Runs with long polling: no public server, webhook or inbound port is needed.

Each Telegram chat maps to one Plane project. Everyone who can send commands in a configured chat can use the bot with the Plane token owner's permissions, including deleting tasks. Use it in chats whose members should have that access.

## Setup from scratch

You need Python 3.13, a Plane account with access to the project, and a Telegram account. Run the terminal commands below from this repository's directory. Keep the bot process running to receive commands and scheduled reports.

### 1. Install

    git clone https://github.com/mdportnov/plane-telegram-bot.git
    cd plane-telegram-bot
    python3.13 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements.txt
    cp .env.example .env
    cp config.example.yaml config.yaml
    cp projects.example.json projects.json
    cp members.example.json members.json

On Windows, use `py -3.13 -m venv .venv`, then `.venv\Scripts\activate`. Copy the four example files with your file manager or PowerShell `Copy-Item` instead of `cp`.

The example project/chat IDs are placeholders. Replace them in step 4. `members.json` starts as `[]`; assignment by Telegram username is optional.

### 2. Create a Telegram bot and get the chat ID

1. Open [@BotFather](https://t.me/BotFather) in Telegram, send `/newbot`, and follow the prompts.
2. Copy its token into `BOT_TOKEN` in `.env`. The token resembles `123456789:AA...`. This is a secret, not the bot's username.
3. Start setup mode, which only needs `BOT_TOKEN`:

       python main.py --telegram-setup

4. For a group: add the bot to the target group and send `/chatid@YourBotUsername` there. For a private chat: open the bot, press **Start**, then send `/chatid`.
5. The bot replies with `Chat ID: -1001234567890` (example). Copy the entire number, including the minus sign, into `chat_id` in `projects.json`.
6. Stop setup mode with **Ctrl+C** before running the normal bot.

The bot needs permission to send messages. Group privacy mode can stay enabled; explicitly address commands as `/command@YourBotUsername`. No third-party ID bot or manual `getUpdates` call is needed. A group chat ID is different from your personal Telegram user ID.

See [Telegram's bot setup tutorial](https://core.telegram.org/bots/tutorial) and [privacy-mode FAQ](https://core.telegram.org/bots/faq#what-messages-will-my-bot-get).

### 3. Connect Plane

In Plane, open **Profile Settings → Personal Access Tokens → Add personal access token**. Copy the token into `API_TOKEN` in `.env`. Older Plane releases may call this section **API Tokens**. Use a token belonging to someone with access to the intended projects. See [Plane authentication](https://developers.plane.so/api-reference/introduction).

Get `WORKSPACE_SLUG` from your browser URL. In `https://app.plane.so/acme/projects/`, the slug is `acme`, not a UUID or the full URL.

For Plane Cloud, `.env` should contain:

    API_TOKEN=your-plane-personal-access-token
    WORKSPACE_SLUG=acme
    BASE_URL=https://api.plane.so
    PLANE_APP_URL=https://app.plane.so
    BOT_TOKEN=your-telegram-bot-token
    MODE=INFO
    PLANE_WORK_ITEMS_ENDPOINT=work-items

For self-hosted Plane, set `BASE_URL` to the server serving its API, for example `https://plane.example.com`, and `PLANE_APP_URL` to the address you open in a browser, usually the same URL. Do not append `/api/v1`, a workspace slug, or a project path. A trailing slash is optional.

`BASE_URL` controls API requests; `PLANE_APP_URL` controls clickable task links. On Cloud these are different hosts. If `PLANE_APP_URL` is omitted, it defaults to `https://app.plane.so` for Cloud or to `BASE_URL` for a self-hosted server.

### 4. Get the Plane project ID and map it to your chat

    python main.py --list-projects

This prints all accessible projects as JSON, including their `id`, `name` and `identifier`. Find your project by name and copy its `id` (UUID). Do not use the short `identifier`, such as `ACME`.

Alternatively, open the project in Plane: in `https://app.plane.so/acme/projects/af0d57f1-107e-4554-91a1-7c15022c16e1/issues/`, the UUID after `/projects/` is the project ID.

Edit **projects.json**:

    [
      {
        "project_id": "af0d57f1-107e-4554-91a1-7c15022c16e1",
        "chat_id": "-1001234567890"
      }
    ]

Replace both values with yours. Add more objects for more project/chat pairs. Each project and each chat must appear only once. JSON allows no comments or trailing commas.

### 5. Optional: map Plane members to Telegram usernames

    python main.py --list-members

This prints workspace members. Each member's `id` is the Plane user UUID used for assignment. To list only a project's members:

    python main.py --list-members --project-id YOUR_PROJECT_UUID

Edit **members.json**, pairing the Plane user's `id` with their Telegram username:

    [
      {
        "member_id": "55c56d6c-13f6-4dd1-be67-a39992eff736",
        "telegram_id": "@alice"
      }
    ]

`telegram_id` is a username, not a numeric Telegram user ID. With or without `@` is accepted; matching is case-insensitive. Ensure each assignee belongs to the target Plane project. Plane cannot infer someone's Telegram username, so this association remains manual even though member IDs are available through the API.

Leave the file as `[]` if you do not need username assignments. Reports still work; unmapped assignees are shown by their Plane ID. Alternatively, set `members_file_path: null` to run without a members file.

### 6. Choose report states and schedule

    python main.py --list-states --project-id YOUR_PROJECT_UUID

Use the exact state names returned by this command in **config.yaml**:

    report_states_list:
      - Todo
      - In Progress
      - In Review
    cron_expression: "0 9 * * mon-fri"
    cron_timezone: "UTC"
    projects_file_path: "projects.json"
    members_file_path: "members.json"

Replace the example state names with your project's names. States vary between projects. The schedule above runs at 09:00 Monday–Friday in `cron_timezone`. Use an IANA timezone such as `Europe/Berlin` or `Africa/Johannesburg`. For a quick schedule test, `*/2 * * * *` means every two minutes. To turn scheduled reports off, set `cron_expression: null`; `/getreport` still works.

Scheduled reports skip projects with no tasks in the selected states. `/getreport` also displays empty states. State names are matched exactly; at runtime each project reports its matching states, while the setup check flags any configured name missing from a project.

Paths to JSON mappings are relative to `config.yaml`. Restart after changing `.env`, mappings, or the schedule. `cron_start_date` is obsolete and ignored. `BOT_NAME` is no longer needed; Telegram supplies the bot's username automatically.

### 7. Check and run

    python main.py --check-config
    python main.py

The check validates files, IDs, timezone, cron, report state names and read access to Plane projects/work items. When a member mapping is present, it also checks workspace membership. Legacy servers without the Members API get an explicit notice that member IDs could not be verified. It does not send messages or modify Plane, and does not validate Telegram delivery or write permissions.

In the mapped Telegram chat, send `/getstates`, then `/getreport`. A successful report confirms Telegram delivery and Plane access. Only run one process per Telegram bot token, including during setup.

## Commands

| Command | Action |
| --- | --- |
| `/start`, `/help` | Show command format and help |
| `/chatid` | Show the current chat's numeric ID; works before mapping |
| `/getstates` | List this project's state names and UUIDs |
| `/getreport` | Send this project's report immediately |
| `/newtask` | Create a task; `Title` required |
| `/updatetask` | Update a task; `UUID` and at least one changed field required |
| `/removetask <UUID>` | Permanently delete a task |

For groups, append `@YourBotUsername` to the command on the first line.

Minimal creation:

    /newtask
    Title: Prepare release

With optional fields:

    /newtask
    Title: Prepare release
    Description: Write release notes.
    Include the migration steps.
    Start: 2026-10-01
    Deadline: 2026-10-05
    Priority: 3
    State: In Progress
    Assignees: @alice @bob

Fields can appear in any order, one per line. Only Description may span multiple lines. A separate line containing `@alice @bob` also works for assignment. Mentions inside the title or description are treated as text. Titles may contain up to 255 characters. Dates accept `YYYY-MM-DD` or `DD-MM-YYYY`; the deadline cannot precede the start date. Priority is `0` = none, `1` = low, `2` = medium, `3` = high, `4` = urgent.

To update, copy the **UUID** shown in a report or creation reply (not the short task number like `ACME-42`):

    /updatetask
    UUID: 12345678-1234-1234-1234-123456789abc
    State: In Progress
    Priority: 4

Omitted fields stay unchanged. Listed assignees are added to existing assignees; use Plane to remove assignees or clear dates. `Description:` with no text clears the description.

## Docker

Complete setup first so `.env`, `config.yaml`, `projects.json` and `members.json` exist, then stop any local bot process and run:

    docker compose up -d --build
    docker compose logs -f bot

Stop it with `docker compose down`. Config and mapping files are mounted read-only. Credentials and local mappings are excluded from the image. After changing `.env`, recreate the container with `docker compose up -d --force-recreate`; for config/mapping changes, restart with `docker compose restart bot`.

CI publishes every tested commit on `master` as `ghcr.io/vyhuholl/plane-telegram-bot:<commit sha>`, for running the bot without building it.

## API compatibility and upgrades

The bot uses [Plane's work-items API](https://developers.plane.so/api-reference/issue/list-issues), `X-API-Key` authentication and cursor pagination. Member discovery uses the [workspace members](https://developers.plane.so/api-reference/members/get-workspace-members) and [project members](https://developers.plane.so/api-reference/members/get-project-members) endpoints. Assignees and named priorities follow the [create work item schema](https://developers.plane.so/api-reference/issue/add-issue).

For an older self-hosted release that only exposes `/issues/`, set `PLANE_WORK_ITEMS_ENDPOINT=issues` in `.env` and restart. This switches all task read/create/update/delete requests. Member discovery still requires a Plane release that supports the Members API. There is no automatic retry of writes, avoiding duplicate tasks when a response is lost.

Existing `.env` names and mapping schemas are retained. Earlier README versions accidentally swapped the examples for `projects.json` and `members.json`; ensure yours match the examples above. The unused `member__display_name` field in old mappings may remain. The old statement that assignment is unsupported no longer reflects the current API contract.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing setting or invalid file | Follow the named setting in the startup error; use the example files. |
| HTTP 401/403 from Plane | Token validity, expiry and permissions; access to the workspace/project. |
| HTTP 404 from Plane | Workspace slug, project/task UUIDs, server URL; for older servers try `PLANE_WORK_ITEMS_ENDPOINT=issues`. |
| Invalid JSON / redirect response | `BASE_URL` must serve the API. For Cloud use `https://api.plane.so`, not `https://app.plane.so`. |
| Bot does not reply in a group | Add it, allow messages, and use `/help@YourBotUsername`. |
| Chat is not configured | Run `/chatid` in that exact chat, update `projects.json`, restart. Supergroup migration can change the ID. |
| Telegram Conflict / getUpdates error | Stop other processes using the same bot token. Remove an existing webhook if reusing a token from another service. |
| Unknown assignee | Use the Telegram username in `members.json`, pair it with the Plane member's `id`, and restart. |
| No report / no matching states | Run `/getstates`, check `report_states_list`, timezone and schedule. Empty scheduled reports are skipped. |
| HTTP 429 | Wait for the rate limit to reset and reduce report frequency. |
| Timeout after a write | Inspect Plane before retrying: the operation may already have succeeded. |

## Development

    python -m pip install -r requirements-dev.txt
    python -m pytest
    python -m ruff check .
    python -m ruff format --check .

Tests use mocked APIs and do not need credentials. `requirements.in` lists direct dependencies; `requirements.txt` pins the resolved runtime dependencies. To refresh it, use `uv pip compile requirements.in --upgrade -o requirements.txt --no-header --no-annotate` and run the checks again.
