"""
Stage 2 & 3 sync logic — smart sync edition.

On every run:
  - Finds active categories in Program Tracker
  - For already-pushed categories: fetches existing sub-tasks and patches
    any missing or outdated due dates and owners (smart update)
  - For newly active categories: creates sub-tasks fresh
  - Never creates duplicates — matches by sub-task name before creating

Column keyword types:
  __always__       → always create tasks for this category (no status check)
  color_*          → color column, active when value is not blank/none
  anything else    → standard status column, active when text not in NA_VALUES
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

# Sub-item column IDs (confirmed from Sprint Board)
COL_DUE_DATE  = "date0"
COL_START_DATE = "date_mm1hwtgt"
COL_OWNER     = "person"


def is_active(col: dict) -> bool:
    """
    Check if a column value means the category is active (not NA).
    Handles standard status columns and color columns.
    """
    col_type = col.get("type", "")
    text = (col.get("text") or "").strip()
    value = col.get("value")

    if col_type == "color":
        # Color columns: active when value is not null/empty
        return value is not None and value != "null" and value != ""
    else:
        # Standard status: active when text is not an NA value
        return text.lower() not in NA_VALUES


def get_active_categories(item_column_values: list[dict]) -> list[str]:
    """
    Return list of category names that are active for this program.
    __always__ categories are always included.
    """
    active = []

    # Build a lookup of col_id -> column data from the item
    col_lookup = {col.get("id", ""): col for col in item_column_values}

    for category, config in TASKS_CONFIG.items():
        if category.startswith("_"):
            continue
        keyword = config.get("monday_column_keyword", "")

        # Always-on categories
        if keyword == "__always__":
            active.append(category)
            continue

        # Status / color column check
        col = col_lookup.get(keyword)
        if col and is_active(col):
            active.append(category)

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


def build_column_values(due_date: str | None) -> dict:
    col = {}
    if due_date:
        col[COL_DUE_DATE] = {"date": due_date}
    return col


def patch_existing_subitems(
    sprint_item_id: str,
    categories: list[str],
    program_dates: dict,
    owner_id: str | None,
    dry_run: bool
):
    """Fetch existing sub-tasks and patch missing/changed due dates and owners."""
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
            if not due_date:
                continue
            print(f"    ~ patch: {name[:70]} | due: {due_date}")
            if not dry_run:
                mc.update_item_column_values(
                    subitem["id"],
                    {COL_DUE_DATE: {"date": due_date}},
                    board_id=subitem["board_id"]
                )
                if owner_id:
                    try:
                        mc.assign_person_to_item(subitem["id"], subitem["board_id"], owner_id)
                    except Exception as e:
                        print(f"      [warn] Could not assign owner: {e}")
            patched += 1

    print(f"  Patched {patched} existing sub-tasks")


def is_due_within_window(due_date_str: str | None, days: int = 14) -> bool:
    """
    Returns True if the due date falls within the next N days from today.
    Tasks with no due date are always created (can't calculate window).
    Tasks overdue (past due) are also created — they need immediate attention.
    """
    if not due_date_str:
        return True  # no due date — create it, better to have it than not
    try:
        from datetime import timedelta
        due = date.fromisoformat(due_date_str)
        today = date.today()
        return due <= today + timedelta(days=days)
    except ValueError:
        return True  # unparseable date — create it


def push_new_subitems(
    sprint_item_id: str,
    categories: list[str],
    program_dates: dict,
    owner_id: str | None,
    dry_run: bool
) -> list[str]:
    """
    Create sub-tasks for each category, skipping duplicates by name.
    Only creates tasks due within the next 14 days — deferred tasks are
    logged and will be picked up automatically on future daily runs.
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
        due_soon = [t for t in tasks if is_due_within_window(t.get("due_date"))]
        deferred = len(tasks) - len(due_soon)
        print(f"  Creating {len(due_soon)} sub-tasks for: {category} ({deferred} deferred — not due within 14 days)")

        for task in due_soon:
            name = build_subitem_name(category, task["name"])
            if name in existing_names:
                print(f"    [skip duplicate] {name[:70]}")
                continue

            due_date = task.get("due_date")
            print(f"    + {name[:70]} | due: {due_date}")

            if not dry_run:
                new_id, subitem_board_id = mc.create_subitem(
                    parent_item_id=sprint_item_id,
                    subitem_name=name
                )
                if new_id:
                    if due_date:
                        try:
                            mc.update_item_column_values(
                                new_id,
                                {COL_DUE_DATE: {"date": due_date}},
                                board_id=subitem_board_id
                            )
                        except Exception as e:
                            print(f"      [warn] Could not set due date {due_date}: {e}")
                    if owner_id:
                        try:
                            mc.assign_person_to_item(new_id, subitem_board_id, owner_id)
                        except Exception as e:
                            print(f"      [warn] Could not assign owner: {e}")
            existing_names.add(name)

        all_tasks = calculate_all_task_dates(config["tasks"], program_dates)
        all_pushed = all(is_due_within_window(t.get("due_date")) or
                        build_subitem_name(category, t["name"]) in existing_names
                        for t in all_tasks)
        if all_pushed:
            pushed_categories.append(category)
        else:
            print(f"  [defer] {category} has future tasks — will re-check on next run")

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

    # Validate sprint_item_id — only reset if item is explicitly confirmed non-existent
    if sprint_item_id:
        exists = mc.item_exists(sprint_item_id)
        if exists is False:
            # Only reset if we are confident the item is gone (False, not None/error)
            print(f"  [heal] Sprint item {sprint_item_id} confirmed gone — creating fresh")
            sprint_item_id = None
            already_pushed = []
            if not dry_run:
                sm.full_reset(program_item_id)
        else:
            print(f"  Sprint item {sprint_item_id} confirmed active")
    # Auto-clean state for categories that are no longer active
    # So if they become active again later, they get pushed fresh
    if already_pushed and not dry_run:
        reverted = [c for c in already_pushed if c not in active_categories]
        if reverted:
            print(f"  [auto-clean] {reverted} are now NA — removing from pushed state")
            sm.remove_categories(program_item_id, reverted)
            already_pushed = sm.get_pushed_categories(program_item_id)

    new_categories = [c for c in active_categories if c not in already_pushed]

    # Self-healing: only re-push categories that are BOTH missing AND still active
    if already_pushed and sprint_item_id:
        try:
            existing = mc.get_subitems(sprint_item_id)
            existing_names = {sub["name"] for sub in existing}
            missing_categories = []
            for category in already_pushed:
                if category not in active_categories:
                    print(f"  [warn] {category} was pushed but is now NA — skipping re-heal")
                    continue
                config = TASKS_CONFIG.get(category)
                if not config:
                    continue
                expected = [build_subitem_name(category, t["name"]) for t in config["tasks"]]
                if not any(name in existing_names for name in expected):
                    missing_categories.append(category)
            if missing_categories:
                print(f"  [heal] Sub-tasks missing for: {missing_categories} — will re-push")
                new_categories = list(set(new_categories + missing_categories))
                if not dry_run:
                    sm.remove_categories(program_item_id, missing_categories)
                    already_pushed = sm.get_pushed_categories(program_item_id)
        except Exception as e:
            print(f"  [warn] Could not verify existing sub-tasks: {e}")

    print(f"\n[sync] {program_name}")
    print(f"  Active:       {active_categories}")
    print(f"  Already done: {already_pushed}")
    print(f"  New to push:  {new_categories}")

    owner_id = resolve_owner_id(user_cache)

    # Create parent sprint item if not yet created
    if not sprint_item_id:
        # First check if item already exists in Monday (prevents duplicates after reset)
        existing_id = mc.find_item_by_name(sprint_board_id, sprint_group_id, program_name)
        if existing_id:
            print(f"  Found existing sprint item: {existing_id} — reusing")
            sprint_item_id = existing_id
            if not dry_run:
                sm.record_push(program_item_id, sprint_item_id, [])
        else:
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


def normalise(s: str) -> str:
    """Lowercase, replace underscores/hyphens with spaces, collapse whitespace."""
    return " ".join(s.lower().replace("_", " ").replace("-", " ").split())


def find_excel_for_program(program_name: str, programs_dir: str) -> str | None:
    from pathlib import Path
    programs_path = Path(programs_dir)
    if not programs_path.exists():
        return None
    prog_norm = normalise(program_name)
    for folder in sorted(programs_path.iterdir()):
        if not folder.is_dir():
            continue
        excel = folder / "program.xlsx"
        if not excel.exists():
            continue
        folder_norm = normalise(folder.name)
        if folder_norm in prog_norm or prog_norm in folder_norm:
            return str(excel)
        # Also check any word-level overlap (e.g. "india pilot 2" in "india pilot 2 program test2")
        folder_words = set(folder_norm.split())
        prog_words = set(prog_norm.split())
        overlap = folder_words & prog_words - {"program", "test", "the", "a", "of"}
        if len(overlap) >= 2:
            return str(excel)
        excel_program_name = get_program_name_from_excel(str(excel))
        if excel_program_name:
            excel_norm = normalise(excel_program_name)
            if excel_norm in prog_norm or prog_norm in excel_norm:
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
        item_id   = item["id"]
        item_name = item["name"]
        col_values = item["column_values"]

        active_categories = get_active_categories(col_values)
        if not active_categories:
            print(f"[skip] {item_name} — no active categories")
            continue

        excel_path = find_excel_for_program(item_name, programs_dir)
        if not excel_path:
            print(f"[skip] {item_name} — no program.xlsx found")
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
