import re
from datetime import date, timedelta


ANCHOR_SYMBOLS = {
    "R": "rfp_date",
    "S": "submission_date",
    "W": "win_date",
    "C": "confirmation_date",
    "P": "program_start_date",
    "PE": "program_end_date",
}

RULE_PATTERN = re.compile(r"^(PE|W|R|S|C|P)([+-]\d+)?$")


def add_working_days(start: date, days: int) -> date:
    """
    Add or subtract working days (Mon-Fri) from a date.
    Positive days = forward, negative days = backward.
    Weekends are skipped entirely.
    """
    if days == 0:
        return start
    direction = 1 if days > 0 else -1
    remaining = abs(days)
    current = start
    while remaining > 0:
        current += timedelta(days=direction)
        if current.weekday() < 5:  # Mon=0 ... Fri=4
            remaining -= 1
    return current


def parse_rule(rule: str) -> tuple[str, int]:
    """
    Parse a rule string like 'W+1', 'C+3', 'P-10', 'PE+5', or bare 'C', 'P'
    into (anchor_key, offset_working_days).
    All offsets are working days (Mon-Fri).
    """
    rule = rule.strip()
    match = RULE_PATTERN.match(rule)
    if not match:
        raise ValueError(f"Cannot parse date rule: '{rule}'. Expected format like W+1, C+3, P-10")

    symbol = match.group(1)
    offset_str = match.group(2)
    anchor_key = ANCHOR_SYMBOLS[symbol]
    offset = int(offset_str) if offset_str else 0
    return anchor_key, offset


def calculate_due_date(rule: str, program_dates: dict) -> date | None:
    """
    Given a rule string and a dict of program dates, return the calculated due date.
    All offsets are working days.

    program_dates keys:
        rfp_date, submission_date, win_date, confirmation_date,
        program_start_date, program_end_date
    """
    anchor_key, offset = parse_rule(rule)
    anchor_date = program_dates.get(anchor_key)

    if anchor_date is None:
        return None

    if isinstance(anchor_date, str):
        anchor_date = date.fromisoformat(anchor_date)

    return add_working_days(anchor_date, offset)


def calculate_all_task_dates(tasks: list[dict], program_dates: dict) -> list[dict]:
    """
    Given a list of task dicts (each with a 'rule' key) and program_dates,
    return the same list with 'due_date' added to each task.
    """
    result = []
    for task in tasks:
        enriched = dict(task)
        rule = task.get("rule", "")
        try:
            due = calculate_due_date(rule, program_dates)
            enriched["due_date"] = due.isoformat() if due else None
        except ValueError as e:
            print(f"  [warn] Skipping bad rule '{rule}': {e}")
            enriched["due_date"] = None
        result.append(enriched)
    return result


def read_legend_from_excel(excel_path: str) -> dict:
    """
    Read anchor dates from the Legend sheet of a program Excel file.
    Returns dict with keys matching ANCHOR_SYMBOLS values.
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required: pip install pandas openpyxl")

    df = pd.read_excel(excel_path, sheet_name="Legend", header=None)

    dates = {}
    for _, row in df.iterrows():
        symbol = str(row[0]).strip() if pd.notna(row[0]) else ""
        raw_date = row[2] if len(row) > 2 else None

        if symbol not in ANCHOR_SYMBOLS:
            continue
        if pd.isna(raw_date):
            continue

        anchor_key = ANCHOR_SYMBOLS[symbol]
        try:
            if hasattr(raw_date, "date"):
                dates[anchor_key] = raw_date.date()
            else:
                dates[anchor_key] = date.fromisoformat(str(raw_date)[:10])
        except (ValueError, TypeError):
            print(f"  [warn] Could not parse date for symbol '{symbol}': {raw_date}")

    return dates


def get_program_name_from_excel(excel_path: str) -> str:
    """Read the program name from the Legend sheet (row 0, col 1)."""
    try:
        import pandas as pd
        df = pd.read_excel(excel_path, sheet_name="Legend", header=None)
        name = str(df.iloc[0, 1]).strip()
        return name if name and name != "nan" else ""
    except Exception:
        return ""
