"""端到端：驱动真实 worker.main() 循环（fake redis，带 BLPOP 阻塞语义）。

运行：cd backend && python -I tests/test_worker_e2e.py

覆盖：worker 自动消费、强杀滞留后按心跳自动恢复重算、重复投递不产生新结果、
共享产物与库内结果一致。
"""
import json, os, shutil, sys, tempfile, threading, time, types

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import fastapi  # noqa: F401
except ModuleNotFoundError:
    fastapi = types.ModuleType("fastapi")
    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail); self.status_code, self.detail = status_code, detail
    fastapi.HTTPException = HTTPException
    sys.modules.setdefault("fastapi", fastapi)

WORK = tempfile.mkdtemp(prefix="qw-e2e-")
os.environ.update({
    "DATABASE_URL": "sqlite:///" + os.path.join(WORK, "e2e.sqlite"),
    "ARTIFACT_DIR": os.path.join(WORK, "artifacts"),
    "TASK_MODE": "inline",
    "RUN_STALE_SECONDS": "1",
    "HEARTBEAT_INTERVAL": "1",
    "RECOVERY_INTERVAL": "1",
    "SEED_DEMO": "false",
})
sys.path.insert(0, BACKEND_ROOT)

# 在 import worker 之前注入 fake redis（仅本测试进程生效）
fake_redis_mod = types.ModuleType("redis")
class FakeRedis:
    def __init__(self): self.q = []; self.cond = threading.Condition()
    def rpush(self, key, value):
        with self.cond:
            self.q.append(value); self.cond.notify_all(); return len(self.q)
    def blpop(self, key, timeout=0):
        deadline = time.time() + timeout
        with self.cond:
            while not self.q:
                remaining = deadline - time.time()
                if remaining <= 0: return None
                self.cond.wait(remaining)
            return (key.encode(), self.q.pop(0).encode())
    @classmethod
    def from_url(cls, url): return _SHARED
_SHARED = FakeRedis()
fake_redis_mod.Redis = FakeRedis
sys.modules["redis"] = fake_redis_mod

from src.utils import repository as repo
from src.services import run as run_service
from src.utils.identity import now
repo.init_db()

import statistics
rows = [{"sample_id": f"M1-{i:03d}", "machine": "M1", "sequence": i,
         "value": round(20.0 + ((i * 37) % 13 - 6) * 0.001 + (0.01 if i >= 80 else 0.0), 5)}
        for i in range(1, 101)]
vals = [r["value"] for r in rows if r["sequence"] <= 60]
repo.put("datasets", {"id": "ds1", "name": "ds", "source": "c.csv", "rows": rows, "created_at": now()})
repo.put("baselines", {"id": "bl1", "name": "bl", "dataset_id": "ds1", "machine": "M1",
                       "start": 1, "end": 60, "values": vals,
                       "mean": statistics.mean(vals), "sigma": statistics.stdev(vals), "created_at": now()})
repo.put("studies", {"id": "st1", "name": "st", "baseline_id": "bl1",
                     "monitoring_start": 61, "monitoring_end": 100,
                     "smoothing": 0.2, "control_width": 3, "lsl": 19.95, "usl": 20.05, "created_at": now()})
class RI:
    def __init__(self, sid): self.study_id = sid

PASS, FAIL = [], []
def check(name, cond):
    (PASS if cond else FAIL).append(name); print(("PASS" if cond else "FAIL"), "-", name)

# 1) 正常入队，worker 自动消费
run = run_service.create(RI("st1"))
repo.put("runs", {**run, "status": "queued", "result": {}, "heartbeat_at": "", "attempts": []})
_SHARED.rpush(run_service.JOB_QUEUE, run["id"])

from src import worker as worker_mod
threading.Thread(target=worker_mod.main, daemon=True).start()
deadline = time.time() + 15
while time.time() < deadline and repo.get("runs", run["id"])["status"] != "completed":
    time.sleep(0.2)
r1 = repo.get("runs", run["id"])
check("E2E 1 worker 自动消费队列并完成", r1["status"] == "completed" and len(r1["result"]["series"]) == 40)
checksum_after_first = r1["result"]["checksum"]

# 2) 模拟 worker 强杀：running 滞留 + 心跳过期，worker 自动恢复重投并重算
r1["status"] = "running"; r1["heartbeat_at"] = "2000-01-01T00:00:00+00:00"; repo.put("runs", r1)
deadline = time.time() + 20
while time.time() < deadline:
    cur = repo.get("runs", run["id"])
    if cur["status"] == "completed" and len(cur.get("attempts", [])) >= 2: break
    time.sleep(0.3)
r2 = repo.get("runs", run["id"])
check("E2E 2 中断后自动恢复并完成", r2["status"] == "completed"
      and any(a.get("recovered") for a in r2["attempts"]))
check("E2E 3 结果仍只有一份且 checksum 不变", r2["result"]["checksum"] == checksum_after_first)

# 3) 重复投递同一运行：claim 被忽略，结果与 attempt 数不变
_SHARED.rpush(run_service.JOB_QUEUE, run["id"])
_SHARED.rpush(run_service.JOB_QUEUE, run["id"])
time.sleep(5)
r3 = repo.get("runs", run["id"])
check("E2E 4 重复投递不产生新 attempt、不覆盖结果",
      r3["status"] == "completed" and len(r3["attempts"]) == len(r2["attempts"])
      and r3["result"]["checksum"] == checksum_after_first)

# 4) 产物文件与库内结果一致
artifact = run_service.ARTIFACT_DIR / (run["id"] + ".json")
check("E2E 5 共享产物与库内结果一致",
      artifact.exists() and json.loads(artifact.read_text())["checksum"] == r3["result"]["checksum"])

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if FAIL else 0)
