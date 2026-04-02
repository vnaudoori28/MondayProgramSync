# monday-program-sync

Automated sync from **Program Tracker** → **Sprint Board** in Monday.com.

When a program manager marks a category as active (transitions from `NA`), this script picks it up and creates formatted sub-tasks in the Sprint Board with due dates calculated from your program's anchor dates.

---

## How it works

| Stage | Trigger | What happens |
|-------|---------|--------------|
| 1 | Native Monday automation (already in place) | New program item created in Sprint Board, assigned to APM |
| 2 | First daily run after handover meeting | Reads active categories, creates sub-tasks with due dates |
| 3 | Subsequent daily runs | Picks up any newly activated categories, adds tasks — no duplicates |

Stages 2 and 3 are the **same script**. State tracking makes it idempotent.

---

## Date calculation

Tasks use rules from your Excel master (e.g. `C+1`, `P-15`):

| Symbol | Meaning | Example rule | Result |
|--------|---------|-------------|--------|
| `C` | Confirmation date | `C+1` | 1 day after client confirms |
| `C+` | Days after confirmation | `C+30` | 30 days after confirmation |
| `P` | Program start date | `P-15` | 15 days before program starts |
| `PE` | Program end date | `PE+3` | 3 days after program ends |

The script reads `C` and `P` dates directly from the Program Tracker board columns.

---

## Setup

### 1. Clone and install

```bash
git clone <your-repo-url>
cd monday-program-sync
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in your `.env`:

```
MONDAY_API_TOKEN=    # Monday → Profile → Admin → API
TRACKER_BOARD_ID=    # Program Tracker board ID
SPRINT_BOARD_ID=     # Sprint board ID  
SPRINT_GROUP_ID=     # Group in Sprint board (e.g. "Programs in Planning")
DEFAULT_TASK_OWNER=  # e.g. Siddhanth Waghmare
```

**Finding board/group IDs:**
- Board ID: open the board → three-dot menu → Board info
- Group ID: use the Monday API or check the board URL when a group is selected

### 3. Map your Monday column IDs

In `src/stage2_sync.py`, the `column_values` dict uses Monday column IDs:

```python
column_values["date4"] = {"date": due_date}   # update to your actual due date column ID
column_values["person"] = ...                  # update to your actual person column ID
```

To find your column IDs: Monday board → Manage columns → click any column → the ID is shown in the URL or via API.

### 4. Map category columns in Program Tracker

In `src/date_calculator.py`, the `COLUMN_KEYWORDS` dict maps anchor date keys to column name patterns. Update these to match your actual Monday column names/IDs:

```python
COLUMN_KEYWORDS = {
    "confirmation_date": ["confirmation", "confirmed"],
    "program_start_date": ["program start", "program date"],
    ...
}
```

---

## Usage

```bash
# Preview what would be pushed (no writes)
python src/main.py --dry-run

# Run the sync
python src/main.py

# See what's already been pushed per program
python src/main.py --show-state

# Re-push a specific program (clears its state then syncs)
python src/main.py --reset 1234567890
```

---

## GitHub Actions (automated daily run)

### Add secrets to your repo

Go to: **Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:
- `MONDAY_API_TOKEN`
- `TRACKER_BOARD_ID`
- `SPRINT_BOARD_ID`
- `SPRINT_GROUP_ID`
- `DEFAULT_TASK_OWNER`

### Schedule

The workflow runs daily at **8:00 AM IST** (2:30 AM UTC). Change the cron in `.github/workflows/daily_sync.yml` if needed.

### Manual trigger

Go to: **Actions → Program Tracker Sync → Run workflow**

Options:
- `dry_run: true` → preview only
- `reset_item_id` → clear state for one program before running

---

## Adding new categories

1. Open `config/tasks.json`
2. Replace any `PLACEHOLDER` task entries with real task names and rules
3. Ensure the `monday_column_keyword` matches what appears in your Program Tracker column ID

---

## State file

`state/pushed_state.json` tracks what's been pushed per program:

```json
{
  "1234567890": {
    "sprint_item_id": "9876543210",
    "pushed_categories": ["Hotels", "Flights"],
    "last_synced": "2026-03-25"
  }
}
```

- Committed to git via GitHub Actions cache — persists between runs
- Edit manually if you need to force a re-push or remove a category
- `pushed_state.json` is gitignored locally so it doesn't get committed from your machine
