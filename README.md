# PlaneAPI Telegram Bot Integration

This project provides a Python-based integration for managing and reporting tasks from Plane.so projects. The bot interacts with the Plane.so API to fetch project details, task statuses, and generates task reports tailored for Telegram.

### Features

- Retrieve all projects in a workspace.
- Fetch tasks for specific projects categorized by statuses (Todo, In Progress, In Review).
- Generate Telegram-ready reports with clickable links to tasks and user profiles.

### Requirements

- Python 3.9+
- requests library for API calls
- Plane.so API key

### Known issues:
1. https://github.com/makeplane/plane/issues/5061 - that's why members.json should be used for mapping
2. in Create Issue API - not working creating assignees