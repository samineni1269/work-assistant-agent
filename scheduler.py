"""
scheduler.py — Automated Daily Scheduling
==========================================
Runs the agent on a schedule in the background.

Default schedule:
  09:00 — Daily briefing (calendar + emails + Jira)
  09:15 — Standup summary (ready to paste into Teams)

Usage:
    python scheduler.py          — run continuously (stays alive, runs jobs daily)
    python scheduler.py now      — run both jobs immediately (for testing)

Configure times in the .env file:
    BRIEFING_TIME=09:00
    STANDUP_TIME=09:15
"""

import os
import sys
import time
import datetime
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
BRIEFING_TIME = os.getenv("BRIEFING_TIME", "09:00")
STANDUP_TIME  = os.getenv("STANDUP_TIME",  "09:15")

AGENT_PATH = Path(__file__).parent / "agent.py"
PYTHON_CMD = sys.executable


def _run_mode(mode: str):
    """Run the agent in a specific mode as a subprocess."""
    print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Running: {mode}")
    result = subprocess.run(
        [PYTHON_CMD, str(AGENT_PATH), mode],
        cwd=str(AGENT_PATH.parent),
    )
    if result.returncode != 0:
        print(f"⚠️  Agent exited with code {result.returncode}")


def run_briefing():
    """Run the daily briefing."""
    _run_mode("briefing")


def run_standup():
    """Run the standup summary."""
    _run_mode("standup")


def _time_to_seconds_until(time_str: str) -> int:
    """Calculate seconds until next occurrence of HH:MM today (or tomorrow if already past)."""
    h, m = map(int, time_str.split(":"))
    now = datetime.datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return int((target - now).total_seconds())


def run_now():
    """Run both jobs immediately (useful for testing)."""
    print("🚀  Running briefing and standup now...")
    run_briefing()
    time.sleep(2)
    run_standup()
    print("\n✅  Done.")


def run_scheduler():
    """Run the scheduler continuously, firing jobs at configured times."""
    print("=" * 60)
    print("  ⏰  Work Assistant Scheduler")
    print("=" * 60)
    print(f"  Daily briefing : {BRIEFING_TIME}")
    print(f"  Standup summary: {STANDUP_TIME}")
    print("\n  Running in background — press Ctrl+C to stop.\n")

    # Track which jobs ran today so we don't double-fire
    last_ran_briefing = None
    last_ran_standup = None

    while True:
        now = datetime.datetime.now()
        today = now.date()
        current_time = now.strftime("%H:%M")

        # Briefing
        if current_time == BRIEFING_TIME and last_ran_briefing != today:
            last_ran_briefing = today
            run_briefing()

        # Standup
        if current_time == STANDUP_TIME and last_ran_standup != today:
            last_ran_standup = today
            run_standup()

        # Print next run times once per minute at :00 seconds
        if now.second == 0:
            secs_briefing = _time_to_seconds_until(BRIEFING_TIME)
            secs_standup  = _time_to_seconds_until(STANDUP_TIME)
            h_b, m_b = divmod(secs_briefing // 60, 60)
            h_s, m_s = divmod(secs_standup // 60, 60)
            print(
                f"  [{current_time}] Next briefing in {h_b}h {m_b}m · "
                f"Next standup in {h_s}h {m_s}m",
                end="\r"
            )

        time.sleep(30)  # Check every 30 seconds


if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "schedule"
    if mode == "now":
        run_now()
    else:
        try:
            run_scheduler()
        except KeyboardInterrupt:
            print("\n\n  Scheduler stopped.")
