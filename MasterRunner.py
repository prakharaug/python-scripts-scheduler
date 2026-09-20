import json
import subprocess
import time
import datetime
import os
import sys
import traceback
import logging
from logging.handlers import RotatingFileHandler
import winsound
from croniter import croniter

def beep_error():
    try:
        winsound.Beep(500, 200)
    except Exception:
        pass


CONFIG_FILE = 'scripts_config.json'
STATE_FILE = 'runner_state.json'
LOG_FILE = 'master_runner.log'

log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('')
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding='utf-8')
file_handler.setFormatter(log_format)
logger.addHandler(file_handler)

console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(log_format)
logger.addHandler(console)

def load_config_data():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"Config file {CONFIG_FILE} not found.")
        return {}
    except json.JSONDecodeError:
        logging.error(f"Error decoding {CONFIG_FILE}. Check JSON format.")
        return {}

def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    # Migrate old plain-timestamp format to new structured format
    migrated = {}
    for key, value in raw.items():
        if isinstance(value, str):
            # Old format: just a timestamp string → convert
            migrated[key] = {
                "last_run": value,
                "status": "success",
                "retry_count": 0
            }
        elif isinstance(value, dict):
            migrated[key] = value
        else:
            migrated[key] = {
                "last_run": None,
                "status": "unknown",
                "retry_count": 0
            }
    return migrated

def save_state(state):
    """Saves the state dictionary."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save state: {e}")

def get_retry_config(script, config):
    """Get max_retries, retry_delay_minutes, and timeout_minutes for a script, with fallback to global defaults."""
    defaults = config.get('defaults', {})
    max_retries = script.get('max_retries', defaults.get('max_retries', 2))
    retry_delay = script.get('retry_delay_minutes', defaults.get('retry_delay_minutes', 5))
    timeout = script.get('timeout_minutes', defaults.get('timeout_minutes', 30))
    return max_retries, retry_delay, timeout

def _parse_last_run_dt(state_entry):
    """Extract last_run datetime from a state entry (structured dict)."""
    if not state_entry:
        return None
    last_run_str = state_entry.get('last_run')
    if not last_run_str:
        return None
    try:
        return datetime.datetime.fromisoformat(last_run_str)
    except ValueError:
        try:
            return datetime.datetime.strptime(last_run_str, "%Y-%m-%d")
        except ValueError:
            return None


def is_script_due(script, state, config):
    """
    Checks if a script is due to run.
    Returns Tuple: (Boolean is_due, String reason)
    """
    path = script.get('path')
    if not path:
        return False, "No Path"

    schedule = script.get('schedule', {})
    sched_type = schedule.get('type', 'daily') # Default to daily if missing

    state_entry = state.get(path, {})
    last_run_dt = _parse_last_run_dt(state_entry)
    last_status = state_entry.get('status', 'success')
    retry_count = state_entry.get('retry_count', 0)

    now = datetime.datetime.now()

    # --- Retry check: if the last run failed and retries remain ---
    max_retries, retry_delay, _ = get_retry_config(script, config)
    if last_status == 'failed' and retry_count < max_retries:
        if last_run_dt:
            minutes_since = (now - last_run_dt).total_seconds() / 60
            if minutes_since >= retry_delay:
                return True, f"Retry {retry_count + 1}/{max_retries} (failed {int(minutes_since)}m ago)"
            else:
                return False, f"Retry waiting ({retry_delay - minutes_since:.0f}m left)"
        else:
            return True, f"Retry {retry_count + 1}/{max_retries} (no last_run timestamp)"

    # If retries are exhausted, treat as "ran" for this schedule window
    # (the normal schedule logic below will re-trigger at the NEXT window)

    # --- Cron Schedule ---
    if sched_type == 'cron':
        cron_expr = schedule.get('expression')
        if not cron_expr:
            return False, "Cron schedule missing 'expression'"
        try:
            cron = croniter(cron_expr, now)
            prev_fire = cron.get_prev(datetime.datetime)
        except (ValueError, KeyError) as e:
            logging.error(f"Invalid cron expression '{cron_expr}' for {path}: {e}")
            return False, f"Invalid cron expression: {cron_expr}"

        # If never ran, or last run was before the most recent fire time → due
        if last_run_dt is None or last_run_dt < prev_fire:
            return True, f"Cron '{cron_expr}' due (fire={prev_fire.strftime('%H:%M')})"
        return False, f"Cron '{cron_expr}' not due (last={last_run_dt.strftime('%H:%M')}, fire={prev_fire.strftime('%H:%M')})"

    # --- Hourly Schedule ---
    if sched_type == 'hourly':
        # Optional: Check 'days' restriction
        allowed_days = schedule.get('days')
        if allowed_days:
            allowed_days = [d.title() for d in allowed_days]
            current_day = now.strftime('%A')
            if current_day not in allowed_days:
                 return False, f"Hourly run skipped (Day {current_day} not in {allowed_days})"

        # Default minute is 0 (top of the hour)
        target_minute = schedule.get('minute', 0)

        # Check if run this hour?
        # We check if last_run_dt is in the current hour of absolute time
        if last_run_dt:
            if last_run_dt.date() == now.date() and last_run_dt.hour == now.hour:
                 return False, f"Already ran this hour ({last_run_dt.strftime('%H:%M')})"

        # Check if we are past the target minute
        if now.minute >= target_minute:
            return True, f"Hourly run due (Minute {target_minute})"
        else:
            return False, f"Waiting for minute {target_minute} (Current: {now.minute})"

    # --- Daily / Weekly / Date Logic ---
    # Common logic: Check if ran TODAY (Day level granularity)
    if last_run_dt and last_run_dt.date() == now.date():
         return False, "Already ran today"

    sched_time_str = schedule.get('time', '11:00')

    # Parse Target Time
    try:
        h, m = map(int, sched_time_str.split(':'))
        target_time = datetime.time(h, m)
    except ValueError:
        logging.error(f"Invalid time {sched_time_str} for {path}")
        return False, "Invalid time format"

    # Check Time Condition (Must be past target time)
    if now.time() < target_time:
        return False, "Too early"

    # Check Day/Date Conditions based on Type
    if sched_type == 'daily':
        return True, "Daily schedule met"

    elif sched_type == 'weekly':
        allowed_days = schedule.get('days', [])
        # Normalise to title case (Monday, Tuesday...)
        allowed_days = [d.title() for d in allowed_days]
        current_day = now.strftime('%A')
        if current_day in allowed_days:
            return True, f"Weekly schedule met ({current_day})"
        return False, f"Wrong day ({current_day} not in {allowed_days})"

    elif sched_type == 'date':
        target_date_str = schedule.get('date') # YYYY-MM-DD
        today_str = datetime.date.today().isoformat()
        if today_str == target_date_str:
            return True, "Specific date met"
        return False, f"Wrong date ({today_str} != {target_date_str})"

    return False, f"Unknown schedule type: {sched_type}"

def run_script(script, timeout_minutes=30):
    """Executes a single script with real-time output streaming and timeout."""
    path = script.get('path')
    description = script.get('description', 'Unknown Script')
    timeout_seconds = timeout_minutes * 60

    abs_path = os.path.abspath(path)
    script_dir = os.path.dirname(abs_path)

    if not os.path.exists(abs_path):
        logging.error(f"Script not found: {abs_path}")
        beep_error()
        return False

    logging.info(f"Running: {description} ({abs_path})")

    try:
        # Force UTF-8 and unbuffered output from child process
        my_env = os.environ.copy()
        my_env["PYTHONUTF8"] = "1"
        my_env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            [sys.executable, abs_path],
            cwd=script_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=my_env
        )

        # Stream stdout line-by-line in real time, with timeout
        import threading
        timed_out = False

        def read_stdout():
            assert process.stdout is not None  # guaranteed by stdout=PIPE above
            for line in process.stdout:
                line = line.rstrip('\n\r')
                if line:
                    logging.info(f"[{description}] {line}")

        reader_thread = threading.Thread(target=read_stdout, daemon=True)
        reader_thread.start()
        reader_thread.join(timeout=timeout_seconds)

        if reader_thread.is_alive():
            # Script exceeded timeout
            timed_out = True
            logging.error(f"Timeout: {description} exceeded {timeout_minutes} minutes. Killing process.")
            process.kill()
            process.wait()
            beep_error()
            return False

        # After stdout closes, read any remaining stderr
        assert process.stderr is not None  # guaranteed by stderr=PIPE above
        stderr_output = process.stderr.read()
        process.wait()

        if process.returncode == 0:
            logging.info(f"Success: {description}")
            return True
        else:
            logging.error(f"Failed: {description} (exit code {process.returncode})")
            if stderr_output:
                logging.error(f"Error Output:\n{stderr_output}")
            beep_error()
            return False

    except Exception as e:
        logging.error(f"Unexpected error running {description}: {e}")
        beep_error()
        return False

def main():
    logging.info("MasterRunner (Granular) started.")

    # Validation run on startup
    config = load_config_data()
    logging.info(f"Loaded {len(config.get('scripts', []))} scripts.")

    while True:
        try:
            # Reload every loop to catch config changes dynamically
            config = load_config_data()
            state = load_state()
            scripts = config.get('scripts', [])

            any_run = False

            for script in scripts:
                is_due, reason = is_script_due(script, state, config)
                path = script.get('path')

                if is_due:
                    logging.info(f"Triggering {script.get('description')} (Reason: {reason})")
                    prev_entry = state.get(path, {})
                    prev_retry_count = prev_entry.get('retry_count', 0)
                    max_retries, _, timeout = get_retry_config(script, config)

                    success = run_script(script, timeout_minutes=timeout)

                    if success:
                        state[path] = {
                            "last_run": datetime.datetime.now().isoformat(),
                            "status": "success",
                            "retry_count": 0
                        }
                    else:
                        new_retry_count = prev_retry_count + 1
                        if new_retry_count >= max_retries:
                            logging.warning(f"Max retries ({max_retries}) exhausted for {script.get('description')}. Will retry at next schedule window.")
                        else:
                            logging.info(f"Will retry {script.get('description')} (attempt {new_retry_count}/{max_retries} in a few minutes)")
                        state[path] = {
                            "last_run": datetime.datetime.now().isoformat(),
                            "status": "failed",
                            "retry_count": new_retry_count
                        }

                    save_state(state)
                    any_run = True

            if any_run:
                logging.info("Cycle completed. Waiting...")
            else:
                logging.info("Heartbeat: No scripts due this cycle.")

        except Exception as e:
            logging.error(f"Critical Loop Error: {e}")
            logging.error(traceback.format_exc())
            beep_error()

        # Sleep for 60 seconds (Polling Interval)
        time.sleep(120)

if __name__ == "__main__":
    main()
