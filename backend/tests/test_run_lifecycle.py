"""漂移复核运行生命周期回归测试（仅标准库，sqlite 驱动同一份服务代码）。

运行：cd backend && python -I tests/test_run_lifecycle.py

覆盖：正常排队执行（快照/attempts/心跳/产物）、中断后自动恢复、重复投递与并发
领取只保留一份结果、迟到旧进程结果不能覆盖新结果、恢复失败留明确原因、终态运行
/已批准复核/报告保持原样、按排队时快照计算、计算失败留因、并发 claim 原子性、
队列配额。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import types
import uuid

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 本地无 fastapi 时打最小桩；容器/CI 已安装则使用真实模块
try:
    import fastapi  # noqa: F401
except ModuleNotFoundError:
    fastapi = types.ModuleType("fastapi")
    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    fastapi.HTTPException = HTTPException
    sys.modules.setdefault("fastapi", fastapi)

WORK = tempfile.mkdtemp(prefix="qw-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(WORK, "test.sqlite")
os.environ["ARTIFACT_DIR"] = os.path.join(WORK, "artifacts")
os.environ["TASK_MODE"] = "inline"
os.environ["RUN_STALE_SECONDS"] = "1"
os.environ["HEARTBEAT_INTERVAL"] = "1"
os.environ["SEED_DEMO"] = "false"
sys.path.insert(0, BACKEND_ROOT)

from src.utils import repository as repo
from src.services import run as run_service
from src.services.statistics import analyze
from src.services import review as review_service
from src.services import report as report_service
from src.utils.identity import now

repo.init_db()

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL"), "-", name, extra)

def make_inputs(empty=False):
    ds_id = "ds-" + uuid.uuid4().hex[:8]
    rows = []
    for seq in range(1, 101):
        rows.append({"sample_id": f"{ds_id}-{seq:03d}", "machine": "M1", "sequence": seq,
                     "value": 20.0 + (seq - 1) * 0.0001})
    repo.put("datasets", {"id": ds_id, "name": "ds", "source": "x.csv", "rows": rows,
                          "created_at": now()})
    import statistics
    vals = [r["value"] for r in rows if r["sequence"] <= 60]
    mu = statistics.mean(vals); sigma = statistics.stdev(vals)
    bl_id = "bl-" + uuid.uuid4().hex[:8]
    repo.put("baselines", {"id": bl_id, "name": "bl", "dataset_id": ds_id, "machine": "M1",
                           "start": 1, "end": 60, "values": vals, "mean": mu, "sigma": sigma,
                           "created_at": now()})
    st_id = "st-" + uuid.uuid4().hex[:8]
    start, end = (90, 89) if empty else (61, 100)
    repo.put("studies", {"id": st_id, "name": "st", "baseline_id": bl_id,
                         "monitoring_start": start, "monitoring_end": end,
                         "smoothing": 0.2, "control_width": 3, "lsl": 19.95, "usl": 20.05,
                         "created_at": now()})
    return ds_id, bl_id, st_id, rows, mu, sigma

class RunInput:
    def __init__(self, study_id): self.study_id = study_id
class ReviewInput:
    def __init__(self, run_id, comment): self.run_id, self.comment = run_id, comment
class DecisionInput:
    def __init__(self, status, comment): self.status, self.comment = status, comment
class ReportInput:
    def __init__(self, run_id, review_id, title):
        self.run_id, self.review_id, self.title = run_id, review_id, title
USER = {"email": "admin@lishi.test", "role": "admin", "name": "x"}

class FakeRedis:
    def __init__(self, fail=False): self.q, self.fail = [], fail
    def rpush(self, key, value):
        if self.fail: raise RuntimeError("redis down")
        self.q.append(value); return len(self.q)

# 1. 正常执行 + 快照 + attempts + 心跳 + 产物
ds, bl, st, rows, mu, sigma = make_inputs()
run = run_service.create(RunInput(st))
check("1.1 inline 执行后为 completed", run["status"] == "completed")
check("1.2 生成结果序列", len(run["result"]["series"]) == 40)
check("1.3 记录一次成功 attempt", len(run["attempts"]) == 1 and run["attempts"][0]["outcome"] == "completed")
check("1.4 固化排队快照", bool(run["queued_study"] and run["queued_baseline"] and run["queued_dataset"]))
check("1.5 快照结果与输入一致 checksum",
      run["result"]["checksum"] == analyze(rows, run["queued_baseline"], run["queued_study"])["checksum"])
check("1.6 产物文件已生成", (run_service.ARTIFACT_DIR / (run["id"] + ".json")).exists())
check("1.7 无临时文件残留", not list(run_service.ARTIFACT_DIR.glob("*.tmp")))
check("1.8 心跳已写入", bool(run["heartbeat_at"]))

# 2. 中断自动恢复
ds2, bl2, st2, *_ = make_inputs()
run2 = run_service.create(RunInput(st2))
run2["status"] = "running"; run2["heartbeat_at"] = "2000-01-01T00:00:00+00:00"; repo.put("runs", run2)
check("2.1 心跳未超时前不可被非恢复调用领取",
      repo.claim_run(run2["id"], "w-old", 99, 60, recover=False)[1] is False)
fake = FakeRedis()
recovered = run_service.recover_stale(fake, "w-recovery")
check("2.2 stale 运行被自动重投", recovered == [run2["id"]] and fake.q == [run2["id"]])
check("2.3 恢复错误字段被清空", repo.get("runs", run2["id"]).get("last_recovery_error", "") == "")
run2b = run_service.execute(run2["id"], worker_id="w-new", recover=True)
check("2.4 恢复重算后 completed", run2b["status"] == "completed")
check("2.5 新增一次 recovered attempt 且原因明确",
      len(run2b["attempts"]) == 2 and run2b["attempts"][-1]["recovered"] is True
      and "心跳中断" in run2b["attempts"][-1]["recover_reason"])

# 3. 重复投递 / 并发领取只有一份结果
ds3, bl3, st3, *_ = make_inputs()
run3 = run_service.create(RunInput(st3))
run3["status"] = "running"; run3["heartbeat_at"] = now(); repo.put("runs", run3)
r, claimed, reason = repo.claim_run(run3["id"], "w-dup", 5, 60, recover=True)
check("3.1 心跳新鲜的 running 拒绝重复领取", claimed is False and "正在其他计算进程" in reason)
run3["status"] = "queued"; run3["heartbeat_at"] = ""; repo.put("runs", run3)
winners = []
def claim(worker):
    _, ok, _ = repo.claim_run(run3["id"], worker, 7, 60, recover=True)
    winners.append((worker, ok))
ts = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
check("3.2 并发 claim 只有一个赢家", sum(1 for _, ok in winners if ok) == 1, str(winners))
win_worker = next(w for w, ok in winners if ok)
repo.finish_run(run3["id"], win_worker, 7, "completed",
                result=analyze(run3["queued_dataset"]["rows"], run3["queued_baseline"], run3["queued_study"]))

# 4. 迟到旧进程结果不能覆盖新结果
ds4, bl4, st4, *_ = make_inputs()
run4 = run_service.create(RunInput(st4))
run4["status"] = "running"; run4["heartbeat_at"] = "2000-01-01T00:00:00+00:00"; repo.put("runs", run4)
r4, ok, _ = repo.claim_run(run4["id"], "w-new", 2, 1, recover=True)
check("4.1 新进程成功恢复领取", ok is True)
stale_result = {"series": [], "poison": True, "checksum": "stale"}
r4b, accepted = repo.finish_run(run4["id"], "w-old", 1, "completed", result=stale_result)
check("4.2 旧 attempt 的迟到结果被拒绝", accepted is False and r4b["status"] == "running")
check("4.3 迟到结果未写入", "poison" not in r4b.get("result", {}))
check("4.4 旧 attempt 心跳被拒绝", repo.touch_run(run4["id"], "w-old", 1) is False)
r4c, accepted = repo.finish_run(run4["id"], "w-new", 2, "completed",
                                result=analyze(run4["queued_dataset"]["rows"],
                                               run4["queued_baseline"], run4["queued_study"]))
check("4.5 当前 attempt 正常完成", accepted and r4c["status"] == "completed"
      and r4c["result"]["checksum"] != "stale")
r4d, accepted = repo.finish_run(run4["id"], "w-zombie", 9, "completed", result=stale_result)
check("4.6 终态后迟到 finish 被拒绝", accepted is False and "poison" not in r4d["result"])

# 5. 恢复失败留下明确原因
ds5, bl5, st5, *_ = make_inputs()
run5 = run_service.create(RunInput(st5))
run5["status"] = "running"; run5["heartbeat_at"] = "2000-01-01T00:00:00+00:00"; repo.put("runs", run5)
run_service.recover_stale(FakeRedis(fail=True), "w-recovery")
r5 = repo.get("runs", run5["id"])
check("5.1 重投失败保留 running 并写明原因", r5["status"] == "running"
      and "自动恢复重投失败" in r5.get("last_recovery_error", ""))
fake2 = FakeRedis()
run_service.recover_stale(fake2, "w-recovery")
check("5.2 Redis 恢复后重投成功并清除原因",
      fake2.q == [run5["id"]] and repo.get("runs", run5["id"])["last_recovery_error"] == "")
run_service.execute(run5["id"], worker_id="w-new", recover=True)

# 6. 已完成运行 / 批准复核 / 报告保持原样
ds6, bl6, st6, rows6, *_ = make_inputs()
run6 = run_service.create(RunInput(st6))
original_checksum = run6["result"]["checksum"]
rev = review_service.create(ReviewInput(run6["id"], "偏差说明超过五个字"), USER)
review_service.decide(rev["id"], DecisionInput("approved", "批准归档说明"), USER)
rep = report_service.create(ReportInput(run6["id"], rev["id"], "归档报告标题"))
r6, claimed, reason = repo.claim_run(run6["id"], "w-x", 3, 1, recover=True)
check("6.1 已完成运行不可再领取", claimed is False and "终态" in reason)
check("6.2 复核保持 approved", repo.get("reviews", rev["id"])["status"] == "approved")
check("6.3 报告保持原样", repo.get("reports", rep["id"])["title"] == "归档报告标题")
check("6.4 结果 checksum 未变", repo.get("runs", run6["id"])["result"]["checksum"] == original_checksum)
csv_text = report_service.download(rep["id"])
check("6.5 报告 CSV 仍可下载且含序列", "sample_id" in csv_text and csv_text.count("\n") > 10)

# 7. 按排队时快照计算：排队后篡改实时实体
ds7, bl7, st7, rows7, mu7, sigma7 = make_inputs()
run7 = run_service.create(RunInput(st7))
snap_checksum = run7["result"]["checksum"]
ds_row = repo.get("datasets", ds7)
for r in ds_row["rows"]:
    if r["sequence"] >= 61: r["value"] = 20.04
repo.put("datasets", ds_row)
st_row = repo.get("studies", st7); st_row["lsl"], st_row["usl"] = 19.0, 21.0
repo.put("studies", st_row)
run7["status"] = "running"; run7["heartbeat_at"] = "2000-01-01T00:00:00+00:00"; repo.put("runs", run7)
run_service.recover_stale(FakeRedis(), "w-r")
run7b = run_service.execute(run7["id"], worker_id="w-new", recover=True)
check("7.1 恢复重算沿用排队时快照，checksum 不变", run7b["result"]["checksum"] == snap_checksum)
check("7.2 快照中的规格仍是排队时的 19.95/20.05",
      run7b["queued_study"]["lsl"] == 19.95 and run7b["result"]["capability"]["lsl"] == 19.95)

# 8. 计算失败留明确原因（空监控窗口）
ds8, bl8, st8, *_ = make_inputs(empty=True)
run8 = run_service.create(RunInput(st8))
check("8.1 空监控窗口标记 failed", run8["status"] == "failed")
check("8.2 失败原因明确", "计算失败" in run8["error"] and "监控区间没有观测" in run8["error"])
check("8.3 失败 attempt 记录原因", run8["attempts"][-1]["outcome"] == "failed" and run8["attempts"][-1]["error"])
fake4 = FakeRedis(); run_service.recover_stale(fake4, "w-r")
check("8.4 failed 运行不被恢复扫描重投", fake4.q == [])
check("8.5 failed 运行不可再领取", repo.claim_run(run8["id"], "w", 2, 1, recover=True)[1] is False)

# 9. 旧数据兼容（无快照/无 attempts 的历史 running 行）
ds9, bl9, st9, *_ = make_inputs()
legacy = {"id": "run-legacy-" + uuid.uuid4().hex[:6], "study_id": st9, "status": "running",
          "result": {}, "error": "", "created_at": now()}
repo.put("runs", legacy)
fake5 = FakeRedis()
run_service.recover_stale(fake5, "w-r")
legacy_after = run_service.execute(legacy["id"], worker_id="w-new", recover=True)
check("9.1 无心跳的历史 running 被判定 stale 并恢复", fake5.q == [legacy["id"]])
check("9.2 历史运行通过实时实体回退计算成功", legacy_after["status"] == "completed"
      and len(legacy_after["result"]["series"]) == 40)

# 10. 队列配额仍然生效
existing = sum(r["status"] in ("queued", "running") for r in repo.all_rows("runs"))
for _ in range(10 - existing):
    d, b, s, *_ = make_inputs()
    r = run_service.create(RunInput(s)); r["status"] = "queued"; repo.put("runs", r)
d, b, s, *_ = make_inputs()
quota_hit = False
try:
    run_service.create(RunInput(s))
except ValueError as e:
    quota_hit = "队列已满" in str(e)
check("10.1 队列配额 10 仍然生效", quota_hit)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if FAIL else 0)
