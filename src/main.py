#!/usr/bin/env python3
"""
monday-program-sync — main entry point

Usage:
  python src/main.py                    # normal sync
  python src/main.py --dry-run          # preview only, no writes
  python src/main.py --show-state       # print current pushed state
  python src/main.py --reset <item_id>  # clear state for one program (re-push)
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add src/ to path so sibling imports work
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

import state_manager as sm
from stage2_sync import sync_program_tracker


def require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        print(f"ERROR: {key} is not set. Check your .env file.")
        sys.exit(1)
    return val


def cmd_show_state():
    state = sm.load_state()
    if not state:
        print("No programs synced yet.")
        return
    print(json.dumps(state, indent=2, default=str))


def cmd_reset(item_id: str):
    state = sm.load_state()
    if item_id not in state:
        print(f"No state found for item ID: {item_id}")
        return
    del state[item_id]
    sm.save_state(state)
    print(f"State cleared for item {item_id}. Next sync will re-push all active categories.")


def cmd_sync(dry_run: bool):
    tracker_board_id = require_env("TRACKER_BOARD_ID")
    sprint_board_id  = require_env("SPRINT_BOARD_ID")
    sprint_group_id  = require_env("SPRINT_GROUP_ID")
    programs_dir     = os.environ.get("PROGRAMS_DIR", "programs")

    sync_program_tracker(
        tracker_board_id=tracker_board_id,
        sprint_board_id=sprint_board_id,
        sprint_group_id=sprint_group_id,
        programs_dir=programs_dir,
        dry_run=dry_run
    )


def main():
    parser = argparse.ArgumentParser(description="Sync Program Tracker → Sprint Board")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to Monday")
    parser.add_argument("--show-state", action="store_true", help="Print current pushed state and exit")
    parser.add_argument("--reset", metavar="ITEM_ID", help="Clear pushed state for a specific program item ID")
    args = parser.parse_args()

    if args.show_state:
        cmd_show_state()
    elif args.reset:
        cmd_reset(args.reset)
    else:
        cmd_sync(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
