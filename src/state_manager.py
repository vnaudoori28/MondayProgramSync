import json
import os
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / "state" / "pushed_state.json"


def load_state() -> dict:
    """
    Load the pushed state from disk.
    Structure:
    {
      "program_item_id": {
        "sprint_item_id": "...",          # ID of the item created in sprint board
        "pushed_categories": ["Hotels", "Flights"],
        "last_synced": "2026-03-01"
      }
    }
    """
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def get_pushed_categories(program_item_id: str) -> list[str]:
    state = load_state()
    return state.get(str(program_item_id), {}).get("pushed_categories", [])


def get_sprint_item_id(program_item_id: str) -> str | None:
    state = load_state()
    return state.get(str(program_item_id), {}).get("sprint_item_id")


def record_push(program_item_id: str, sprint_item_id: str, categories: list[str]):
    """
    Record that a set of categories have been pushed for a program.
    Merges with any previously pushed categories (additive, never removes).
    """
    from datetime import date
    state = load_state()
    key = str(program_item_id)

    existing = state.get(key, {})
    already_pushed = set(existing.get("pushed_categories", []))
    all_pushed = sorted(already_pushed | set(categories))

    state[key] = {
        "sprint_item_id": sprint_item_id or existing.get("sprint_item_id"),
        "pushed_categories": all_pushed,
        "last_synced": date.today().isoformat()
    }
    save_state(state)


def remove_categories(program_item_id: str, categories: list[str]):
    """Remove specific categories from pushed state so they get re-pushed next run."""
    state = load_state()
    key = str(program_item_id)
    if key not in state:
        return
    existing = set(state[key].get("pushed_categories", []))
    state[key]["pushed_categories"] = sorted(existing - set(categories))
    save_state(state)


def is_program_known(program_item_id: str) -> bool:
    state = load_state()
    return str(program_item_id) in state
