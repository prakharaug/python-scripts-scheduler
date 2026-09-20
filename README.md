# Python Scripts Scheduler

A single background daemon (`MasterRunner.py`) that runs your other Python scripts on a schedule — daily, weekly, one-off date, cron expression, or hourly. No per-script Task Scheduler entries; one task runs the daemon, which polls a JSON config every 2 minutes.

Features: retries with backoff on failure, per-script timeout kill, rotating logs, catch-up runs if the PC was off at the scheduled time, and an audible beep on failure.

## Quick start

```
pip install -r requirements.txt
copy scripts_config.example.json scripts_config.json
python MasterRunner.py
```

Then edit `scripts_config.json` to point at your own scripts.

See [Scheduler_Setup_Instructions.md](Scheduler_Setup_Instructions.md) for schedule syntax and running it as a Windows background task via Task Scheduler.
