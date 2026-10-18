"""Isolated, explicitly reviewed public browser collection with hard budgets."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from ..scrapers.models import ScrapeResult, ScraperRecipe

MAX_REQUESTS = 120
MAX_BYTES = 40_000_000


def eligible(recipe: ScraperRecipe) -> bool:
    return (recipe.metadata.get("public_browser") is True
            and recipe.metadata.get("partial_listing") is True
            and recipe.pagination.max_pages is not None
            and recipe.pagination.max_pages <= 5)


class BrowserBudget:
    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds
        self.requests = 0
        self.bytes = 0
        self.error = None

    def check(self):
        if self.error or time.monotonic() >= self.deadline:
            raise RuntimeError(self.error or "Public browser time budget exhausted")

    def request(self, url):
        from urllib.parse import urlsplit
        self.check()
        self.requests += 1
        if urlsplit(url).scheme != "https" or self.requests > MAX_REQUESTS:
            self.error = "Public browser HTTPS/request budget exhausted"
            self.check()

    def finished(self, request):
        try:
            response = request.response()
            if response and not (300 <= response.status < 400 or response.status in {204, 205}):
                self.bytes += len(response.body())
                if self.bytes > MAX_BYTES:
                    self.error = "Public browser aggregate byte budget exhausted"
            self.check()
        except Exception:
            self.error = self.error or "Public browser response accounting failed"


def collect_browser(recipe, *, deadline, limiter):
    if not eligible(recipe):
        raise ValueError("Public browser source requires reviewed opt-in and bounded partial coverage")
    guards = []
    process = None
    try:
        for host in sorted(recipe.allowed_hosts):
            guards.append((host, limiter.acquire(host, deadline)))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Public browser source deadline exhausted")
        keys = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH"}
        environment = {key: value for key, value in os.environ.items() if key.upper() in keys}
        process = subprocess.Popen([sys.executable, "-m", "server.public_jobs.browser"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, cwd=Path(__file__).resolve().parents[2], start_new_session=os.name != "nt")
        raw, _ = process.communicate(json.dumps({"recipe": recipe.model_dump(mode="json"), "seconds": remaining}).encode(), timeout=remaining)
        if process.returncode or len(raw) > MAX_BYTES:
            raise RuntimeError("Isolated public browser collection failed")
        return ScrapeResult.model_validate(json.loads(raw))
    finally:
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        for host, guard in reversed(guards):
            limiter.last[host] = time.monotonic()
            guard.release()


if __name__ == "__main__":
    from ..scrapers.runtime import run_scraper
    payload = json.loads(sys.stdin.buffer.read(1_000_001))
    recipe = ScraperRecipe.model_validate(payload["recipe"])
    if not eligible(recipe):
        raise SystemExit(2)
    budget = BrowserBudget(min(180, max(1, float(payload["seconds"]))))
    result = run_scraper(recipe, browser_policy=budget)
    budget.check()
    sys.stdout.buffer.write(result.model_dump_json().encode("utf-8"))
