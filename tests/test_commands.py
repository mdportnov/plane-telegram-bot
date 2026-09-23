import pytest

from bot.commands import build_task_data, parse_task_message, task_id_from_fields

MEMBER = "55c56d6c-13f6-4dd1-be67-a39992eff736"


def test_priority_and_multiline_description_with_mentions():
    fields = parse_task_message(
        "/newtask@ExampleBot\nPriority: 3\nTitle: Contact @alice\nDescription: a < b\nEmail a@b.com\nState: In Progress\nAssignees: @ALICE"
    )
    result = build_task_data(fields, {MEMBER: "@alice"}, {"state-id": "In Progress"})
    assert result["priority"] == "high"
    assert result["name"] == "Contact @alice"
    assert result["description_html"] == "<p>a &lt; b<br>Email a@b.com</p>"
    assert result["assignees"] == [MEMBER]
    assert result["state"] == "state-id"


@pytest.mark.parametrize("priority", ["0", "1", "2", "3", "4"])
def test_all_priorities(priority):
    assert build_task_data({"Title": "x", "Priority": priority}, {})["priority"] in (
        "none",
        "low",
        "medium",
        "high",
        "urgent",
    )


def test_partial_update_leaves_assignees_untouched():
    data = build_task_data({"Title": "Next"}, {}, old_task={"assignees": [MEMBER]})
    assert data == {"name": "Next"}


def test_update_adds_and_deduplicates_assignees():
    data = build_task_data(
        {"Assignees": "@alice, @alice"}, {MEMBER: "Alice"}, old_task={"assignees": ["existing", MEMBER]}
    )
    assert data["assignees"] == ["existing", MEMBER]


def test_move_both_dates_beyond_old_deadline():
    data = build_task_data(
        {"Start": "01-10-2026", "Deadline": "2026-10-05"},
        {},
        old_task={"start_date": "2026-01-01", "target_date": "2026-01-05"},
    )
    assert data["start_date"] == "2026-10-01"


def test_single_date_update_checks_retained_deadline():
    with pytest.raises(ValueError, match="Deadline"):
        build_task_data({"Start": "2026-10-01"}, {}, old_task={"target_date": "2026-01-05"})


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"Title": ""},
        {"Title": "x" * 256},
        {"Title": "x", "Priority": "5"},
        {"Title": "x", "Start": "2026-02-30"},
        {"Title": "x", "State": "Missing"},
        {"Title": "x", "Assignees": "@missing"},
        {"Title": "x", "Assignees": ""},
    ],
)
def test_invalid_input_fails_before_write(fields):
    with pytest.raises(ValueError):
        build_task_data(fields, {})


def test_255_character_title_is_valid():
    assert len(build_task_data({"Title": "x" * 255}, {})["name"]) == 255


def test_legacy_assignee_line_and_bot_suffix():
    fields = parse_task_message("/newtask@MyBot\nTitle: x\n@alice @bob")
    assert fields == {"Title": "x", "Assignees": "@alice @bob"}


@pytest.mark.parametrize("text", ["/newtask\nTitle: x\nTitle: y", "/newtask\nTitle: x\nPriorty: 3"])
def test_ambiguous_fields_rejected(text):
    with pytest.raises(ValueError):
        parse_task_message(text)


def test_uuid_rejects_short_identifier():
    with pytest.raises(ValueError, match="UUID"):
        task_id_from_fields({"UUID": "TEAM-42"})


def test_update_requires_actual_changes():
    with pytest.raises(ValueError, match="at least one"):
        build_task_data({"UUID": MEMBER}, {}, old_task={"name": "Original"})
