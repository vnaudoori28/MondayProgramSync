import re
from datetime import date, timedelta


ANCHOR_SYMBOLS = {
    "R": "rfp_date",
    "S": "submission_date",
    "C": "confirmation_date",
    "P": "program_start_date",
    "PE": "program_end_date",
}

RULE_PATTERN = re.compile(r"^(PE|R|S|C|P)([+-])(\d+)$")


def parse_rule(rule: str) -> tuple[str, int]:
    """
    Parse a rule string like 'C+1', 'P-15', 'PE+3' into (anchor_key, offset_days).
    anchor_key matches keys in program_dates dict.
    offset_days is positive (after) or negative (before) the anchor.
    """
    rule = rule.strip()
    match = RULE_PATTERN.match(rule)
    if not match:
        raise ValueError(f"Cannot parse date rule: '{rule}'. Expected format like C+1, P-15, PE+3")

    symbol, sign, days = match.groups()
    anchor_key = ANCHOR_SYMBOLS[symbol]
    offset = int(days) if sign == "+" else -int(days)
    return anchor_key, offset


def calculate_due_date(rule: str, program_dates: dict) -> date | None:
    """
    Given a rule string and a dict of program dates, return the calculated due date.

    program_dates should contain any relevant keys from ANCHOR_SYMBOLS values:
    {
        "rfp_date": date(...),
        "submission_date": date(...),
        "confirmation_date": date(...),   # C
        "program_start_date": date(...),  # P
        "program_end_date": date(...),    # PE
    }

    Returns None if the required anchor date is not available.
    """
    anchor_key, offset = parse_rule(rule)
    anchor_date = program_dates.get(anchor_key)

    if anchor_date is None:
        return None

    if isinstance(anchor_date, str):
        anchor_date = date.fromisoformat(anchor_date)

    return anchor_date + timedelta(days=offset)


def calculate_all_task_dates(tasks: list[dict], program_dates: dict) -> list[dict]:
    """
    Given a list of task dicts (each with a 'rule' key) and program_dates,
    return the same list with 'due_date' added to each task.
    Tasks where the anchor date is missing get due_date=None.
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


def extract_program_dates_from_item(column_values: list[dict]) -> dict:
    """
    Extract program date anchors from a Monday item's column values.
    Looks for columns whose title/id contains known keywords.

    Returns a dict with keys matching ANCHOR_SYMBOLS values.
    Extend the COLUMN_KEYWORDS map below as your board evolves.
    """
    COLUMN_KEYWORDS = {
        "confirmation_date": ["confirmation", "confirmed", "go-ahead", "go ahead"],
        "program_start_date": ["program start", "program date", "start date", "departure"],
        "program_end_date": ["program end", "end date", "return date"],
        "rfp_date": ["rfp", "rfp date", "received rfp"],
        "submission_date": ["submission", "proposal date"],
    }

    dates = {}
    for col in column_values:
        col_id_lower = col.get("id", "").lower()
        col_text = col.get("text", "") or ""

        for anchor_key, keywords in COLUMN_KEYWORDS.items():
            if anchor_key in dates:
                continue
            if any(kw in col_id_lower for kw in keywords):
                if col_text:
                    try:
                        # Monday returns dates as YYYY-MM-DD
                        from datetime import date as dt
                        dates[anchor_key] = dt.fromisoformat(col_text[:10])
                    except ValueError:
                        pass

    return dates
