# Master Script Setup Instructions

You have a master script (`MasterRunner.py`) that manages the execution of your other scripts.
It runs as a background process ("Daemon") so it only needs to be started **once per PC session**.

## 0. Install Dependencies

```
pip install -r requirements.txt
```

## 1. Configuration

Copy `scripts_config.example.json` to `scripts_config.json` (this file is gitignored, so your personal schedule stays local) and add the scripts you want to run.

```json
{
  "scripts": [
    {
      "path": "path/to/script1.py",
      "description": "Daily Sales",
      "schedule": { "type": "daily", "time": "11:00" }
    },
    {
      "path": "path/to/backup.py",
      "description": "Weekly Backup",
      "schedule": {
        "type": "weekly",
        "days": ["Monday", "Friday"],
        "time": "22:00"
      }
    }
  ]
}
```

### Scheduling Options

**1. Daily Schedule**
Runs every day at the specified time.

```json
"schedule": { "type": "daily", "time": "09:30" }
```

**2. Weekly Schedule**
Runs only on specific days.

```json
"schedule": {
    "type": "weekly",
    "days": ["Monday", "Wednesday", "Friday"],
    "time": "11:00"
}
```

**3. Specific Date (One-off)**
Runs once on a specific date.

```json
"schedule": {
    "type": "date",
    "date": "2025-12-31",
    "time": "23:59"
}
```

**4. Cron Expression (Advanced)**
Use standard cron syntax for any schedule pattern.

```json
"schedule": {
    "type": "cron",
    "expression": "*/15 * * * *"
}
```

**Cron Format:** `minute hour day-of-month month day-of-week`

| Field | Values |
|---|---|
| Minute | 0–59 |
| Hour | 0–23 |
| Day of Month | 1–31 |
| Month | 1–12 |
| Day of Week | 0–6 (Sun=0) or MON–SUN |

**Common Examples:**

| Expression | Meaning |
|---|---|
| `*/15 * * * *` | Every 15 minutes |
| `0 */2 * * *` | Every 2 hours |
| `0 10 * * MON-FRI` | 10 AM on weekdays |
| `0 11,14 * * *` | At 11:00 and 14:00 daily |
| `0 9 1 * *` | 9 AM on the 1st of each month |
| `30 8 * * 1` | 8:30 AM every Monday |

> **Tip:** Use [crontab.guru](https://crontab.guru/) to build and test cron expressions.

## 2. Task Scheduler Setup

You only need to create **ONE** task.

1.  Open **Task Scheduler**.
2.  Click **Create Task...** (right sidebar).
3.  **General Tab**:
    - Name: `Master Python Script Runner`
    - Select **Run only when user is logged on**.
    - Check **Run with highest privileges** (optional, but good if scripts need it).
4.  **Triggers Tab**:
    - Click **New...**
    - Begin the task: **At log on**.
    - Specific user: (Your user).
    - Click **OK**.
5.  **Actions Tab**:
    - Click **New...**.
    - Action: **Start a program**.
    - Program/script: `C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python313\pythonw.exe`
    - Add arguments: `MasterRunner.py`
    - Start in: the folder where `MasterRunner.py` lives (e.g. `C:\Users\<YourUsername>\Scripts Scheduler`).
    - Click **OK**.
6.  **Conditions Tab**:
    - Uncheck "Start the task only if the computer is on AC power" (if you want it to run on battery).
7.  **Settings Tab**:
    - Uncheck "Stop the task if it runs longer than..." (Important! We want it to run forever).
    - Click **OK**.

## 3. How it Works

- When you log in, the script starts silently in the background.
- **Polling Loop**: It wakes up every **1 minute** to check your list of scripts.
- **Checks**:
  - Is it the right **Day**?
  - Is it past the scheduled **Time**?
  - Has it already run **Today**?
- If all checks pass, it runs the script immediately.
- This handles "catch-up" automatically: if you turn on your PC at 1 PM, any 11 AM scripts will run within 1 minute.

## 4. Maintenance

- **Logs**: Check `master_runner.log` to see what happened.
- **Stopping**: Since it runs in the background, use Task Manager to find `python` processes if you need to kill it, or just sign out.
