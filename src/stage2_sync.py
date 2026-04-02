"""
Stage 2 & 3 sync logic.

Reads Program Tracker → finds active categories → diffs against pushed state
→ creates new sub-tasks in Sprint Board for any newly active categories.

Stages 2 and 3 use identical logic. The first run after kickoff is "Stage 2",
subsequent runs that pick up newly activated categories are "Stage 3".
The state file is what makes them idempotent.
"""

import json
import os
from datetime import date

import monday_client as mc
import state_manager as sm
from date_calculator import calculate_all_task_dates, read_legend_from_excel, get_program_name_from_excel

TASKS_CONFIG = json.load(open(
    os.path.join(os.path.dirname(__file__), "..", "config", "tasks.json")
))

# Column value that means "not yet applicable" in Program Tracker
NA_VALUES = {"na", "n/a", "", "none"}

# The status value(s) that mean a category IS active/applicable.
# Monday status columns return the label text in 'text'.
# We treat anything that is NOT an NA value as active.
ACTIVE_CHECK = lambda text: text.strip().lower() not in NA_VALUES if text else False


def get_active_categories(item_column_values: list[dict]) -> list[str]:
    """
    Given an item's column_values from Program Tracker,
    return list of category names that are now active (not NA).
    Matches against the monday_column_keyword in tasks.json.
    """
    active = []
    for category, config in TASKS_CONFIG.items():
        if category.startswith("_"):
            continue
        keyword = config.get("monday_column_keyword", category).lower()
        for col in item_column_values:
            col_id = col.get("id", "").lower()
            col_text = col.get("text", "") or ""
            if keyword in col_id and ACTIVE_CHECK(col_text):
                active.append(category)
                break
    return active


def build_subitem_name(category: str, task_name: str) -> str:
    return f"{category} | {task_name}"


def get_or_resolve_owner_id(owner_name: str, user_cache: dict) -> str | None:
    """
    Resolve a display name to a Monday user ID.
    user_cache is a dict of {name_lower: user_id} built once per run.
    """
    if not owner_name:
        return None
    name_lower = owner_name.strip().lower()
    return user_cache.get(name_lower)


def build_user_cache() -> dict:
    """Fetch all Monday users and return {name_lower: id}."""
    try:
        users = mc.get_users()
        return {u["name"].lower(): u["id"] for u in users}
    except Exception as e:
        print(f"  [warn] Could not fetch Monday users: {e}")
        return {}


def push_categories_for_program(
    program_item_id: str,
    program_name: str,
    sprint_board_id: str,
    sprint_group_id: str,
    categories_to_push: list[str],
    program_dates: dict,
    user_cache: dict,
    dry_run: bool = False
) -> str:
    """
    Push sub-tasks for the given categories under the program's sprint item.
    Creates the sprint parent item if it doesn't exist yet.
    Returns the sprint_item_id.
    """
    sprint_item_id = sm.get_sprint_item_id(program_item_id)

    # Create parent item in sprint board if not yet created
    if not sprint_item_id:
        print(f"  Creating sprint item for: {program_name}")
        if not dry_run:
            sprint_item_id = mc.create_item(
                board_id=sprint_board_id,
                group_id=sprint_group_id,
                item_name=program_name
            )
        else:
            sprint_item_id = "DRY_RUN_ITEM"
        print(f"  Sprint item created: {sprint_item_id}")

    pushed_categories = []

    for category in categories_to_push:
        config = TASKS_CONFIG.get(category)
        if not config:
            print(f"  [skip] No config found for category: {category}")
            continue

        tasks = calculate_all_task_dates(config["tasks"], program_dates)
        print(f"  Pushing {len(tasks)} tasks for category: {category}")

        for task in tasks:
            subitem_name = build_subitem_name(category, task["name"])
            due_date = task.get("due_date")

            column_values = {}
            if due_date:
                column_values["Due Date"] = {"date": due_date}  # update column ID as needed

            owner_name = task.get("owner", "")
            if not owner_name:
                # Default owner from env if set
                owner_name = os.environ.get("DEFAULT_TASK_OWNER", "")

            owner_id = get_or_resolve_owner_id(owner_name, user_cache)
            if owner_id:
                column_values["Owner"] = {"personsAndTeams": [{"id": owner_id, "kind": "person"}]}

            print(f"    + {subitem_name[:80]} | due: {due_date}")
            if not dry_run:
                mc.create_subitem(
                    parent_item_id=sprint_item_id,
                    subitem_name=subitem_name,
                    column_values=column_values if column_values else None
                )

        pushed_categories.append(category)

    if not dry_run and pushed_categories:
        sm.record_push(program_item_id, sprint_item_id, pushed_categories)

    return sprint_item_id


def find_excel_for_program(program_name: str, programs_dir: str) -> str | None:
    """
    Look for a program.xlsx inside programs/<folder> where the folder name or
    the Excel's own program name matches the Monday item name.
    Returns the full path to the Excel file, or None if not found.
    """
    from pathlib import Path
    programs_path = Path(programs_dir)
    if not programs_path.exists():
        return None

    for folder in sorted(programs_path.iterdir()):
        if not folder.is_dir():
            continue
        excel = folder / "program.xlsx"
        if not excel.exists():
            continue

        # Match by folder name (case-insensitive substring)
        if program_name.lower() in folder.name.lower() or folder.name.lower() in program_name.lower():
            return str(excel)

        # Match by program name stored inside the Excel legend
        excel_program_name = get_program_name_from_excel(str(excel))
        if excel_program_name and (
            program_name.lower() in excel_program_name.lower() or
            excel_program_name.lower() in program_name.lower()
        ):
            return str(excel)

    return None


def sync_program_tracker(
    tracker_board_id: str,
    sprint_board_id: str,
    sprint_group_id: str,
    programs_dir: str,
    dry_run: bool = False
):
    """
    Main sync function. Reads all items from Program Tracker,
    matches each to a program Excel file in programs_dir,
    finds newly active categories, and pushes tasks to Sprint Board.

    programs_dir structure:
        programs/
            2026-10_India_Pilot/
                program.xlsx    ← PM fills in Legend dates at kickoff
            2026-11_Singapore/
                program.xlsx
    """
    print(f"\n{'='*60}")
    print(f"Starting sync {'[DRY RUN] ' if dry_run else ''}— {date.today()}")
    print(f"{'='*60}")

    print("Fetching Program Tracker items...")
    items = mc.get_board_items(tracker_board_id)
    print(f"Found {len(items)} programs in tracker\n")

    user_cache = build_user_cache()
    total_new = 0

    for item in items:
        item_id = item["id"]
        item_name = item["name"]
        col_values = item["column_values"]

        active_categories = get_active_categories(col_values)
        if not active_categories:
            print(f"[skip] {item_name} — no active categories")
            continue

        already_pushed = sm.get_pushed_categories(item_id)
        new_categories = [c for c in active_categories if c not in already_pushed]

        if not new_categories:
            print(f"[skip] {item_name} — no new categories (pushed: {already_pushed})")
            continue

        print(f"\n[sync] {item_name}")
        print(f"  Active:      {active_categories}")
        print(f"  Already done:{already_pushed}")
        print(f"  Pushing now: {new_categories}")

        # Find the Excel file for this program
        excel_path = find_excel_for_program(item_name, programs_dir)
        if not excel_path:
            print(f"  [skip] No program.xlsx found in {programs_dir} for '{item_name}'")
            print(f"         Create: programs/<folder-matching-program-name>/program.xlsx")
            continue

        print(f"  Excel: {excel_path}")
        program_dates = read_legend_from_excel(excel_path)

        if not program_dates:
            print(f"  [warn] No dates found in Legend sheet — due dates will be empty")
        else:
            print(f"  Dates loaded: {list(program_dates.keys())}")

        push_categories_for_program(
            program_item_id=item_id,
            program_name=item_name,
            sprint_board_id=sprint_board_id,
            sprint_group_id=sprint_group_id,
            categories_to_push=new_categories,
            program_dates=program_dates,
            user_cache=user_cache,
            dry_run=dry_run
        )
        total_new += len(new_categories)

    print(f"\n{'='*60}")
    print(f"Sync complete. New category pushes: {total_new}")
    print(f"{'='*60}\n")
