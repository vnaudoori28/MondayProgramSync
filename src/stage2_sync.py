"""
Stage 2 & 3 sync logic — smart sync edition.

On every run:
  - Finds active categories in Program Tracker
  - For already-pushed categories: fetches existing sub-tasks and patches
    any missing or outdated due dates and owners (smart update)
  - For newly active categories: creates sub-tasks fresh
  - Never creates duplicates — matches by sub-task name before creating
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

NA_VALUES = {"na", "n/a", "", "none"}
ACTIVE_CHECK = lambda text: text.strip().lower() not in NA_VALUES if text else False

# Sub-item column IDs (confirmed from your Sprint Board)
COL_DUE_DATE = "date0"
COL_START_DATE = "date_mm1hwtgt"
COL_OWNER = "person"


def get_active_categories(item_column_values: list[dict]) -> list[str]:
    active = []
    for category, config in TASKS_CONFIG.items():
        if category.startswith("_"):
            continue
        keyword = config.get("monday_column_keyword", category).lower()
        for col in item_column_values:
            col_id = col.get("id", "").lower()
            col_text = col.get("text", "") or ""
            if keyword == col_id and ACTIVE_CHECK(col_text):
                active.append(category)
                break
    return active


def build_subitem_name(category: str, task_name: str) -> str:
    return f"{category} | {task_name}"


def build_user_cache() -> dict:
    try:
        users = mc.get_users()
        return {u["name"].lower(): u["id"] for u in users}
    except Exception as e:
        print(f"  [warn] Could not fetch Monday users: {e}")
        return {}


def resolve_owner_id(user_cache: dict) -> str | None:
    owner_name = os.environ.get("DEFAULT_TASK_OWNER", "")
    if not owner_name:
        return None
    return user_cache.get(owner_name.strip().lower())


def build_column_values(due_date: str | None, owner_id: str | None) -> dict:
    col = {}
    if due_date:
        col[COL_DUE_DATE] = {"date": due_date}
    if owner_id:
        col[COL_OWNER] = {"personsAndTeams": [{"id": owner_id, "kind": "person"}]}
    return col


def patch_existing_subitems(
    sprint_item_id: str,
    categories: list[str],
    program_dates: dict,
    owner_id: str | None,
    dry_run: bool
):
    """
    Fetch existing sub-tasks, match by name, patch missing/changed due dates and owners.
    """
    print(f"  Fetching existing sub-tasks for smart sync...")
    try:
        existing = mc.get_subitems(sprint_item_id)
    except Exception as e:
        print(f"  [warn] Could not fetch sub-tasks: {e}")
        return

    existing_map = {sub["name"]: {"id": sub["id"], "board_id": sub["board"]["id"]} for sub in existing}
    patched = 0

    for category in categories:
        config = TASKS_CONFIG.get(category)
        if not config:
            continue
        tasks = calculate_all_task_dates(config["tasks"], program_dates)
        for task in tasks:
            name = build_subitem_name(category, task["name"])
            subitem = existing_map.get(name)
            if not subitem:
                continue

            due_date = task.get("due_date")
            col = build_column_values(due_date, owner_id)
            if not col:
                continue

            print(f"    ~ patch: {name[:70]} | due: {due_date}")
            if not dry_run:
                mc.update_item_column_values(subitem["id"], col, board_id=subitem["board_id"])
            patched += 1

    print(f"  Patched {patched} existing sub-tasks")


def push_new_subitems(
    sprint_item_id: str,
    categories: list[str],
    program_dates: dict,
    owner_id: str | None,
    dry_run: bool
) -> list[str]:
    """
    Create sub-tasks for each category, skipping any that already exist by name.
    Returns list of categories successfully pushed.
    """
    print(f"  Fetching existing sub-tasks to check for duplicates...")
    try:
        existing = mc.get_subitems(sprint_item_id)
        existing_names = {sub["name"] for sub in existing}
    except Exception as e:
        print(f"  [warn] Could not fetch sub-tasks for duplicate check: {e}")
        existing_names = set()

    pushed_categories = []
    for category in categories:
        config = TASKS_CONFIG.get(category)
        if not config:
            print(f"  [skip] No config for category: {category}")
            continue

        tasks = calculate_all_task_dates(config["tasks"], program_dates)
        print(f"  Creating {len(tasks)} sub-tasks for: {category}")

        for task in tasks:
            name = build_subitem_name(category, task["name"])
            if name in existing_names:
                print(f"    [skip duplicate] {name[:70]}")
                continue

            due_date = task.get("due_date")
            col = build_column_values(due_date, owner_id)

            print(f"    + {name[:70]} | due: {due_date}")
            if not dry_run:
                # Step 1: create sub-item, get back id + board_id
                new_id, subitem_board_id = mc.create_subitem(
                    parent_item_id=sprint_item_id,
                    subitem_name=name
                )
                # Step 2: patch columns using the subitem's own board_id
                if col and new_id:
                    mc.update_item_column_values(new_id, col, board_id=subitem_board_id)
            existing_names.add(name)

        pushed_categories.append(category)

    return pushed_categories


def sync_program(
    program_item_id: str,
    program_name: str,
    sprint_board_id: str,
    sprint_group_id: str,
    active_categories: list[str],
    program_dates: dict,
    user_cache: dict,
    dry_run: bool
):
    sprint_item_id = sm.get_sprint_item_id(program_item_id)
    already_pushed = sm.get_pushed_categories(program_item_id)
    new_categories = [c for c in active_categories if c not in already_pushed]

    print(f"\n[sync] {program_name}")
    print(f"  Active:       {active_categories}")
    print(f"  Already done: {already_pushed}")
    print(f"  New to push:  {new_categories}")

    owner_id = resolve_owner_id(user_cache)

    # Create parent sprint item if it doesn't exist yet
    if not sprint_item_id:
        print(f"  Creating sprint item...")
        if not dry_run:
            sprint_item_id = mc.create_item(
                board_id=sprint_board_id,
                group_id=sprint_group_id,
                item_name=program_name
            )
        else:
            sprint_item_id = "DRY_RUN_ITEM"
        print(f"  Sprint item: {sprint_item_id}")

    # Smart patch: update dates/owner on already-pushed sub-tasks
    if already_pushed and sprint_item_id and sprint_item_id != "DRY_RUN_ITEM":
        print(f"\n  Smart sync — patching existing sub-tasks...")
        patch_existing_subitems(
            sprint_item_id=sprint_item_id,
            categories=already_pushed,
            program_dates=program_dates,
            owner_id=owner_id,
            dry_run=dry_run
        )

    # Create sub-tasks for newly active categories
    if new_categories:
        print(f"\n  Creating sub-tasks for new categories...")
        pushed = push_new_subitems(
            sprint_item_id=sprint_item_id,
            categories=new_categories,
            program_dates=program_dates,
            owner_id=owner_id,
            dry_run=dry_run
        )
        if not dry_run and pushed:
            sm.record_push(program_item_id, sprint_item_id, pushed)


def find_excel_for_program(program_name: str, programs_dir: str) -> str | None:
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
        if program_name.lower() in folder.name.lower() or folder.name.lower() in program_name.lower():
            return str(excel)
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
    print(f"\n{'='*60}")
    print(f"Starting sync {'[DRY RUN] ' if dry_run else ''}— {date.today()}")
    print(f"{'='*60}")

    print("Fetching Program Tracker items...")
    items = mc.get_board_items(tracker_board_id)
    print(f"Found {len(items)} programs in tracker\n")

    user_cache = build_user_cache()

    for item in items:
        item_id = item["id"]
        item_name = item["name"]
        col_values = item["column_values"]

        active_categories = get_active_categories(col_values)
        if not active_categories:
            print(f"[skip] {item_name} — no active categories")
            continue

        excel_path = find_excel_for_program(item_name, programs_dir)
        if not excel_path:
            print(f"[skip] {item_name} — no program.xlsx found in {programs_dir}")
            print(f"       Create: programs/<folder-matching-program-name>/program.xlsx")
            continue

        print(f"  Excel: {excel_path}")
        program_dates = read_legend_from_excel(excel_path)
        if not program_dates:
            print(f"  [warn] No dates in Legend sheet — due dates will be empty")
        else:
            print(f"  Dates: {list(program_dates.keys())}")

        sync_program(
            program_item_id=item_id,
            program_name=item_name,
            sprint_board_id=sprint_board_id,
            sprint_group_id=sprint_group_id,
            active_categories=active_categories,
            program_dates=program_dates,
            user_cache=user_cache,
            dry_run=dry_run
        )

    print(f"\n{'='*60}")
    print(f"Sync complete — {date.today()}")
    print(f"{'='*60}\n")
