import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram.error import TelegramError

from bot.bot import PlaneNotifierBot
from bot.service.api import PlaneAPI, PlaneAPIError
from bot.utils.logger_config import configure_logging
from bot.utils.utils import (
    load_config_from_file,
    load_members_from_file,
    load_projects_from_file,
    validate_uuid,
)


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return value


def make_api(config=None, members=None):
    slug = required_env("WORKSPACE_SLUG")
    if "/" in slug or any(char.isspace() for char in slug):
        raise ValueError("WORKSPACE_SLUG is the workspace name in the URL, not the full URL.")
    return PlaneAPI(
        required_env("API_TOKEN"),
        slug,
        config,
        members,
        base_url=os.getenv("BASE_URL") or "https://api.plane.so",
        app_url=os.getenv("PLANE_APP_URL") or None,
        mode=os.getenv("MODE") or "INFO",
        work_items_endpoint=os.getenv("PLANE_WORK_ITEMS_ENDPOINT") or "work-items",
    )


def check_config(api, config, projects, members):
    if not projects:
        raise ValueError("projects.json is empty. Add a project ID and chat ID before checking setup.")
    for project_id in projects:
        project = api.get_project(project_id)
        states = api.map_states_by_ids(project_id)
        missing = set(config["report_states_list"]) - set(states.values())
        if missing:
            raise ValueError(
                f"{project['name']}: unknown report states: {', '.join(sorted(missing))}. Use --list-states."
            )
        api.get_project_tasks(project_id)
        print(f"OK: {project['name']} — project, states and work items accessible")
    if members:
        try:
            available = {member["id"] for member in api.get_members()}
        except PlaneAPIError as error:
            if error.status_code != 404 or api.work_items_endpoint != "issues":
                raise
            print("Note: this legacy server has no Members API; member IDs could not be verified.")
        else:
            unknown = set(members) - available
            if unknown:
                raise ValueError(f"Member IDs absent from the workspace: {', '.join(sorted(unknown))}")
    print(
        "Configuration and Plane API checks passed. Telegram delivery is checked with /getreport after startup."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Plane Telegram bot and setup helpers")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--list-projects", action="store_true", help="Print Plane projects and their UUIDs as JSON"
    )
    actions.add_argument(
        "--list-members", action="store_true", help="Print Plane members and their UUIDs as JSON"
    )
    actions.add_argument(
        "--list-states", action="store_true", help="Print project state names and UUIDs as JSON"
    )
    actions.add_argument(
        "--check-config", action="store_true", help="Validate configuration and read access to Plane"
    )
    actions.add_argument(
        "--telegram-setup", action="store_true", help="Run /chatid and /help using only BOT_TOKEN"
    )
    parser.add_argument("--project-id", help="Project UUID for --list-states or --list-members")
    parser.add_argument(
        "--config", default="config.yaml", help="Config path; mappings resolve relative to this file"
    )
    args = parser.parse_args(argv)
    load_dotenv(Path.cwd() / ".env")
    configure_logging(os.getenv("MODE") or "INFO")
    try:
        if args.project_id:
            args.project_id = validate_uuid(args.project_id, "--project-id")
            if not (args.list_states or args.list_members):
                raise ValueError("--project-id is only used with --list-states or --list-members.")
        if args.list_states and not args.project_id:
            raise ValueError("--list-states requires --project-id <UUID>.")
        if args.telegram_setup:
            PlaneNotifierBot(required_env("BOT_TOKEN")).run()
            return 0
        if args.list_projects or args.list_members or args.list_states:
            api = make_api()
            if args.list_projects:
                data = api.get_all_projects()
            elif args.list_members:
                data = api.get_members(args.project_id)
            else:
                data = api.get_task_states_ids(args.project_id)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        config = load_config_from_file(args.config)
        members = load_members_from_file(config["members_file_path"])
        projects = load_projects_from_file(config["projects_file_path"])
        api = make_api(config, members)
        if args.check_config:
            check_config(api, config, projects, members)
            return 0
        if not projects:
            raise ValueError("projects.json is empty. Use --telegram-setup to get your chat ID first.")
        PlaneNotifierBot(required_env("BOT_TOKEN"), api, config, members, projects).run()
        return 0
    except (ValueError, PlaneAPIError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except TelegramError as error:
        print(
            f"Telegram startup failed ({type(error).__name__}). Check BOT_TOKEN, network access, "
            "and whether another process uses this bot token.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
