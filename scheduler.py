# scheduler.py — Daily scraper scheduler
import asyncio
import os
import subprocess
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ── Global reference to scheduler ────────────────────────
_scheduler = None

# ── Main scraper job ──────────────────────────────────────
async def run_daily_scraper():
    """Runs scraper.py daily, pushes to GitHub, hot-reloads KB"""
    print(f"[SCRAPER] Starting daily scrape at {datetime.now()}")
    try:
        GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
        GITHUB_REPO = os.getenv("GITHUB_REPO", "")

        if not GITHUB_TOKEN or not GITHUB_REPO:
            print("[SCRAPER] ERROR: GITHUB_TOKEN or GITHUB_REPO not set!")
            return

        # ── Step 1: Run scraper.py ───────────────────────
        result = subprocess.run(
            ["python", "scraper.py"],
            capture_output=True,
            text=True,
            timeout=1800
        )
        print(f"[SCRAPER] Output:\n{result.stdout}")
        if result.stderr:
            print(f"[SCRAPER] Errors:\n{result.stderr}")

        # ── Step 2: Check if files changed ───────────────
        check = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True
        )

        if not check.stdout.strip():
            print("[SCRAPER] No new pages found — nothing to commit")
            return True  # Still return True so KB reloads

        # ── Step 3: Git config ────────────────────────────
        subprocess.run(["git", "config", "user.email", "astrovedbot@gmail.com"])
        subprocess.run(["git", "config", "user.name", "AstroVed Scraper Bot"])

        # ── Step 4: Set remote with token ─────────────────
        remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        subprocess.run(["git", "remote", "set-url", "origin", remote_url])

        # ── Step 5: Add files ─────────────────────────────
        subprocess.run(["git", "add", "knowledge_base.txt", "all_urls.txt"])

        # ── Step 6: Commit ────────────────────────────────
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run([
            "git", "commit", "-m",
            f"[Auto] Daily scrape update {date_str}"
        ])

        # ── Step 7: Push to GitHub ────────────────────────
        push_result = subprocess.run(
            ["git", "push", "origin", "main"],
            capture_output=True,
            text=True
        )

        if push_result.returncode == 0:
            print("[SCRAPER] ✅ Pushed to GitHub successfully!")
        else:
            print(f"[SCRAPER] ❌ Push failed:\n{push_result.stderr}")

        return True

    except subprocess.TimeoutExpired:
        print("[SCRAPER] ❌ Timed out after 30 minutes!")
        return False
    except Exception as e:
        print(f"[SCRAPER] ❌ Failed: {e}")
        return False


# ── Start scheduler ───────────────────────────────────────
def start_scheduler(reload_kb_callback):
    """
    Call this from main.py lifespan
    reload_kb_callback = function to reload KB after scraping
    """
    global _scheduler

    async def scraper_job():
        success = await run_daily_scraper()
        if success:
            reload_kb_callback()
            print("[SCRAPER] ✅ KB reloaded after scrape!")

    _scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        scraper_job,
        trigger="cron",
        hour=3,
        minute=0,
        id="daily_scraper"
    )
    _scheduler.start()

    next_run = _scheduler.get_job("daily_scraper").next_run_time
    print(f"[SCHEDULER] ✅ Daily scraper scheduled at 3 AM IST")
    print(f"[SCHEDULER] Next run: {next_run}")
    return _scheduler


# ── Stop scheduler ────────────────────────────────────────
def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        print("[SCHEDULER] Stopped")


# ── Manual trigger ────────────────────────────────────────
async def trigger_now(reload_kb_callback):
    """Call this from /admin/scrape-now endpoint"""
    success = await run_daily_scraper()
    if success:
        reload_kb_callback()
        print("[SCRAPER] ✅ KB reloaded after manual trigger!")
    return success