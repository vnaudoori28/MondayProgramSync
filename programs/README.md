# programs/

This folder contains one subfolder per program. Each subfolder holds a
`program.xlsx` with the Legend dates filled in by the Program Manager.

---

## How to add a new program

1. **Copy the template folder**
   ```
   cp -r programs/_template programs/2026-10_India_Pilot
   ```
   Name the folder to match (or partially match) the program name in Monday.

2. **Open `program.xlsx` and fill in the Legend sheet**

   Update the **Date** column (column C) for each symbol:

   | Symbol | Meaning              | Fill in                        |
   |--------|----------------------|-------------------------------|
   | R      | RFP received date    | Actual date RFP was received  |
   | S      | Submission date      | Proposal submission deadline  |
   | C      | Confirmation date    | Date client confirmed program |
   | P      | Program start date   | First day of program          |
   | PE     | Program end date     | Last day of program           |

   Leave symbols blank if not applicable — tasks using that anchor will
   be created without a due date.

3. **Commit and push**
   ```
   git add programs/2026-10_India_Pilot/
   git commit -m "add: 2026-10 India Pilot program dates"
   git push
   ```

4. **The sync runs automatically** at 8 AM IST daily.
   Or trigger it manually from GitHub Actions → Program Tracker Sync → Run workflow.

---

## Folder naming

The script matches folder names to Monday program item names using a
partial, case-insensitive match. So:

| Monday item name                  | Folder name that matches        |
|-----------------------------------|---------------------------------|
| `2026-10 India Pilot Program Test`| `2026-10_India_Pilot` ✓        |
| `2026-10 India Pilot Program Test`| `India_Pilot_2026` ✓           |
| `2026-10 India Pilot Program Test`| `singapore_2026` ✗             |

When in doubt, use the program code (e.g. `2026-10`) in the folder name —
it will always match since it appears in the Monday item name.

---

## Template

`_template/program.xlsx` is the master template. Never edit this directly —
always copy it to a new folder for each program.
