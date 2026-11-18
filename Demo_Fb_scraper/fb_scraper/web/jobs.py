"""Quản lý một collector tại một thời điểm; nhật ký giới hạn trong bộ nhớ."""
from collections import deque
from datetime import datetime, timezone
import json
import subprocess
import sys
import threading
from uuid import uuid4

from fb_scraper.common.paths import PROJECT_ROOT
from fb_scraper.web.worker import EVENT_PREFIX


class JobManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs = deque(maxlen=20)
        self.process = None

    def snapshot(self):
        with self.lock:
            jobs = [{key: value for key, value in job.items() if key != "logs"} for job in self.jobs]
            current = {**jobs[0], "logs": list(self.jobs[0]["logs"])} if jobs else None
            return {"current": current, "history": jobs}

    def start(self, config):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError("Đang có một lượt chạy. Hãy chờ hoàn tất hoặc dừng lượt hiện tại.")
            job = {"id": uuid4().hex, "status": "running", "action": config.get("action", "collect"),
                   "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
                   "completed": 0, "total": len(config.get("plan", [])), "label": "Đang khởi động…",
                   "sources": config.get("plan", []), "logs": deque(maxlen=600), "stop_requested": False}
            arguments = [sys.executable, "-X", "utf8", "-u", "-B", "-m", "fb_scraper.web.worker"]
            process = subprocess.Popen(arguments, cwd=PROJECT_ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.process = process
            self.jobs.appendleft(job)
            try:
                process.stdin.write(json.dumps(config, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except OSError:
                process.terminate()
                process.wait(timeout=5)
                job["status"] = "failed"
                raise
            threading.Thread(target=self._watch, args=(process, job), daemon=True).start()
            return job["id"]

    def _watch(self, process, job):
        try:
            for line in process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                with self.lock:
                    if line.startswith(EVENT_PREFIX):
                        try:
                            event = json.loads(line[len(EVENT_PREFIX):])
                            for key in ("completed", "total", "label"):
                                if key in event:
                                    job[key] = event[key]
                        except ValueError:
                            job["logs"].append(line)
                    else:
                        job["logs"].append(line)
            code = process.wait()
        finally:
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
        with self.lock:
            job["status"] = "cancelled" if job["stop_requested"] and code in (0, 130) else (
                "completed" if code == 0 else "failed")
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
            job["exit_code"] = code

    def stop(self):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                return False
            job = self.jobs[0]
            if not job["stop_requested"]:
                job["stop_requested"] = True
                job["status"] = "stopping"
                job["label"] = "Đang dừng và lưu dữ liệu…"
                try:
                    self.process.stdin.write("stop\n")
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            return True

    def close(self):
        self.stop()
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
