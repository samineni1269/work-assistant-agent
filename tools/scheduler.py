"""
tools/scheduler.py — Scheduled Task Runner
===========================================
Create recurring or one-shot agent queries that run automatically
on a cron schedule.  Uses APScheduler (already in requirements.txt)
+ a local SQLite database for persistence across restarts.

Schema:
  scheduled_tasks(id, name, cron_expr, query, tool_id,
                  enabled, created_at, last_run, next_run,
                  run_count, last_result)

Cron expression examples:
  "0 8 * * *"      — every day at 08:00
  "0 9 * * 1"      — every Monday at 09:00
  "*/30 * * * *"   — every 30 minutes
  "0 0 * * *"      — midnight every day
"""

import datetime
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path.home() / ".work-assistant-scheduler.db"
_scheduler = None
_sched_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            cron_expr   TEXT    NOT NULL,
            query       TEXT    NOT NULL,
            tool_id     TEXT    DEFAULT 'home',
            enabled     INTEGER DEFAULT 1,
            created_at  TEXT    NOT NULL,
            last_run    TEXT    DEFAULT '',
            next_run    TEXT    DEFAULT '',
            run_count   INTEGER DEFAULT 0,
            last_result TEXT    DEFAULT ''
        )
    """)
    conn.commit()
    return conn


def list_tasks() -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_task(name: str, cron_expr: str, query: str,
             tool_id: str = "home") -> dict:
    conn = _get_db()
    now = datetime.datetime.now().isoformat()
    cur = conn.execute(
        """INSERT INTO scheduled_tasks (name, cron_expr, query, tool_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (name, cron_expr, query, tool_id, now),
    )
    conn.commit()
    task_id = cur.lastrowid
    row = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)
    ).fetchone()
    conn.close()
    result = dict(row)
    # Register with APScheduler
    _schedule_task(result)
    return result


def delete_task(task_id: int) -> dict:
    conn = _get_db()
    conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    _unschedule_task(task_id)
    return {"status": "deleted", "id": task_id}


def toggle_task(task_id: int, enabled: bool) -> dict:
    conn = _get_db()
    conn.execute(
        "UPDATE scheduled_tasks SET enabled=? WHERE id=?",
        (int(enabled), task_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)
    ).fetchone()
    conn.close()
    task = dict(row)
    if enabled:
        _schedule_task(task)
    else:
        _unschedule_task(task_id)
    return task


def update_last_run(task_id: int, result: str):
    conn = _get_db()
    now = datetime.datetime.now().isoformat()
    conn.execute(
        """UPDATE scheduled_tasks
           SET last_run=?, run_count=run_count+1, last_result=?
           WHERE id=?""",
        (now, result[:1000], task_id),
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# APSCHEDULER
# ══════════════════════════════════════════════════════════════════════════════

def get_scheduler():
    global _scheduler
    with _sched_lock:
        if _scheduler is None:
            try:
                from apscheduler.schedulers.background import BackgroundScheduler
                _scheduler = BackgroundScheduler(daemon=True)
                _scheduler.start()
                _reload_all_tasks()
            except Exception as e:
                print(f"⚠️  Scheduler unavailable: {e}")
    return _scheduler


def _reload_all_tasks():
    """Schedule all enabled tasks from the DB into APScheduler."""
    try:
        tasks = list_tasks()
        for task in tasks:
            if task["enabled"]:
                _schedule_task(task)
    except Exception:
        pass


def _schedule_task(task: dict):
    sched = get_scheduler()
    if sched is None:
        return
    job_id = f"task_{task['id']}"
    try:
        sched.remove_job(job_id)
    except Exception:
        pass
    try:
        from apscheduler.triggers.cron import CronTrigger
        trigger = CronTrigger.from_crontab(task["cron_expr"])
        sched.add_job(
            _run_scheduled_task,
            trigger=trigger,
            id=job_id,
            args=[task["id"], task["query"], task["tool_id"]],
            replace_existing=True,
            misfire_grace_time=300,
        )
    except Exception as e:
        print(f"⚠️  Scheduler: could not schedule task {task['id']} ({task['name']}): {e}")


def _unschedule_task(task_id: int):
    sched = _scheduler
    if sched is None:
        return
    try:
        sched.remove_job(f"task_{task_id}")
    except Exception:
        pass


def _run_scheduled_task(task_id: int, query: str, tool_id: str):
    """Execute a scheduled task by running an agent query."""
    try:
        from agent import run_agent_turn
        response, _, _ = run_agent_turn([], query, auto_confirm=True)
        update_last_run(task_id, response)
    except Exception as e:
        update_last_run(task_id, f"Error: {e}")


def get_next_run(task_id: int) -> str:
    """Return the next scheduled run time for a task (ISO string or '')."""
    sched = _scheduler
    if sched is None:
        return ""
    try:
        job = sched.get_job(f"task_{task_id}")
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    except Exception:
        pass
    return ""
