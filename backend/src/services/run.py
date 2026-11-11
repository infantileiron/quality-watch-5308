import json
import logging
import os
import socket
import threading
import uuid

from src.models.entities import ControlRun
from src.utils import repository as repo
from src.utils.identity import new_id, now, age_seconds
from src.services.statistics import analyze
from src.config.settings import TASK_MODE, REDIS_URL, ARTIFACT_DIR, RUN_STALE_SECONDS, HEARTBEAT_INTERVAL

logger = logging.getLogger(__name__)
JOB_QUEUE = "quality-watch:jobs"

def list_runs():
    return repo.all_rows("runs")

def worker_identity():
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"

def _load_inputs(run):
    """优先使用排队时快照，保证按排队时的测量数据、基线和方案计算。

    升级前创建的运行没有快照；这些实体（数据集行、基线、方案）均为 insert-only，
    实时引用与排队时内容一致，作为兼容回退。
    """
    if run.get("queued_study") and run.get("queued_baseline") and run.get("queued_dataset"):
        return run["queued_dataset"], run["queued_baseline"], run["queued_study"]
    study = repo.get("studies", run["study_id"])
    baseline = repo.get("baselines", study["baseline_id"])
    dataset = repo.get("datasets", baseline["dataset_id"])
    return dataset, baseline, study

def _is_stale(run):
    age = age_seconds(run.get("heartbeat_at"))
    return age is None or age >= RUN_STALE_SECONDS

def execute(id, worker_id="inline", recover=False):
    """领取并完成一次计算。

    重复投递、多进程并发领取由 claim_run 的事务状态机串行化；崩溃中断的运行
    在心跳超时后由 recover=True 的恢复调用重新领取。终态运行永不重算。
    """
    run = repo.get("runs", id)
    attempt_no = len(run.get("attempts") or []) + 1
    run, claimed, reason = repo.claim_run(id, worker_id, attempt_no, RUN_STALE_SECONDS, recover=recover)
    if not claimed:
        logger.info("运行 %s 领取被忽略：%s（worker=%s）", id, reason, worker_id)
        return run

    stop = threading.Event()
    def heartbeat():
        while not stop.wait(HEARTBEAT_INTERVAL):
            if not repo.touch_run(id, worker_id, attempt_no):
                logger.warning("运行 %s 第%d次尝试已不再是当前尝试，心跳停止（worker=%s）", id, attempt_no, worker_id)
                return
    threading.Thread(target=heartbeat, name=f"hb-{id[:12]}", daemon=True).start()

    tmp_path = None
    try:
        dataset, baseline, study = _load_inputs(run)
        result = analyze(dataset["rows"], baseline, study)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        safe_worker = worker_id.replace("/", "_")
        tmp_path = ARTIFACT_DIR / f"{id}.attempt{attempt_no}.{safe_worker}.tmp"
        tmp_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        run, accepted = repo.finish_run(id, worker_id, attempt_no, "completed", result=result)
        if accepted:
            os.replace(tmp_path, ARTIFACT_DIR / f"{id}.json")
            logger.info("运行 %s 第%d次尝试完成（worker=%s）", id, attempt_no, worker_id)
        else:
            logger.warning("运行 %s 第%d次尝试迟到，结果已拒绝覆盖（worker=%s）", id, attempt_no, worker_id)
        return run
    except Exception as exc:
        logger.exception("运行 %s 第%d次尝试计算失败（worker=%s）", id, attempt_no, worker_id)
        message = f"计算失败：{type(exc).__name__}: {exc}"
        run, _ = repo.finish_run(id, worker_id, attempt_no, "failed", error=message)
        return run
    finally:
        stop.set()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

def recover_stale(client, worker_id):
    """把心跳中断的运行重新投队，使计算自动恢复。重投失败要留下明确原因。"""
    recovered = []
    for run in repo.all_rows("runs"):
        if run.get("status") != "running" or not _is_stale(run):
            continue
        try:
            client.rpush(JOB_QUEUE, run["id"])
            repo.note_recovery(run["id"], "")
            recovered.append(run["id"])
            logger.warning("运行 %s 心跳中断，已自动恢复重投（worker=%s）", run["id"], worker_id)
        except Exception as exc:
            reason = f"自动恢复重投失败：{type(exc).__name__}: {exc}"
            logger.exception("运行 %s %s", run["id"], reason)
            repo.note_recovery(run["id"], reason)
    return recovered

def create(data):
    repo.get("studies", data.study_id)
    if sum(r["status"] in ("queued", "running") for r in repo.all_rows("runs")) >= 10:
        raise ValueError("运行队列已满，请等待已有任务完成")
    # 排队瞬间固化测量数据、基线与方案快照，恢复重算口径与首次排队一致
    study = repo.get("studies", data.study_id)
    baseline = repo.get("baselines", study["baseline_id"])
    dataset = repo.get("datasets", baseline["dataset_id"])
    run = ControlRun(new_id("run"), data.study_id, created_at=now())
    run.queued_study = study
    run.queued_baseline = baseline
    run.queued_dataset = dataset
    run = repo.put("runs", run)
    if TASK_MODE == "inline":
        return execute(run["id"], worker_id="inline")
    try:
        import redis
        redis.Redis.from_url(REDIS_URL).rpush(JOB_QUEUE, run["id"])
    except Exception:
        run["status"] = "failed"
        run["error"] = "队列不可用，请恢复Redis后重新提交"
        repo.put("runs", run)
        raise ValueError(run["error"])
    return run
