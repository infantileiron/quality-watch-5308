import json, sqlite3, threading
from dataclasses import asdict
from fastapi import HTTPException
from src.config.settings import DATABASE_URL
from src.utils.identity import age_seconds, now as now_ts
TABLES = ("datasets", "baselines", "studies", "runs", "reviews", "reports", "users", "audit")
_LOCK = threading.RLock()
def connect():
    if DATABASE_URL.startswith("sqlite:///"):
        conn = sqlite3.connect(DATABASE_URL.removeprefix("sqlite:///"), timeout=30)
        return conn, "?"
    import psycopg
    return psycopg.connect(DATABASE_URL), "%s"
def _is_sqlite():
    return DATABASE_URL.startswith("sqlite:///")
def init_db():
    conn,_ = connect()
    try:
        if not _is_sqlite():
            conn.execute("SELECT pg_advisory_xact_lock(2207)")
        for table in TABLES:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.commit()
    finally: conn.close()
def all_rows(table):
    assert table in TABLES
    conn,_ = connect()
    try: return [json.loads(row[0]) for row in conn.execute(f"SELECT payload FROM {table} ORDER BY id").fetchall()]
    finally: conn.close()
def get(table, id):
    assert table in TABLES
    conn,q = connect()
    try:
        row = conn.execute(f"SELECT payload FROM {table} WHERE id={q}", (id,)).fetchone()
        if row is None: raise HTTPException(404, "记录不存在")
        return json.loads(row[0])
    finally: conn.close()
def put(table, item, insert_only=False):
    assert table in TABLES
    if not isinstance(item, dict): item = asdict(item)
    conn,q = connect()
    clause = "DO NOTHING" if insert_only else "DO UPDATE SET payload=excluded.payload"
    try:
        with _LOCK:
            conn.execute(f"INSERT INTO {table} (id,payload) VALUES ({q},{q}) ON CONFLICT(id) {clause}", (item["id"], json.dumps(item, ensure_ascii=False, allow_nan=False)))
            conn.commit()
        return item
    finally: conn.close()

# --- ControlRun 计算生命周期：事务级原子状态机 ---------------------------------
# 所有状态迁移都在单条数据库事务内完成并对目标运行加写锁，保证多 worker 并发
# 领取、重复投递与崩溃恢复时同一运行只会产生一份被接受的结果。
def _locked_run(conn, q, run_id):
    if _is_sqlite():
        conn.execute("BEGIN IMMEDIATE")
    else:
        # psycopg3 默认 autocommit=False，首条语句即开启事务，FOR UPDATE 锁到提交
        conn.execute(f"SELECT payload FROM runs WHERE id={q} FOR UPDATE", (run_id,))
    row = conn.execute(f"SELECT payload FROM runs WHERE id={q}", (run_id,)).fetchone()
    if row is None:
        conn.rollback(); conn.close()
        raise HTTPException(404, "记录不存在")
    return json.loads(row[0])

def _commit_run(conn, q, run):
    conn.execute(f"UPDATE runs SET payload={q} WHERE id={q}",
                 (json.dumps(run, ensure_ascii=False, allow_nan=False), run["id"]))
    conn.commit(); conn.close()

def claim_run(run_id, worker_id, attempt_no, stale_after, at=None, recover=False):
    """原子领取一次计算。返回 (run, claimed, reason)。

    queued 总是可领取；running 仅在心跳超过 stale_after 秒（判定旧进程已中断）
    且 recover=True 时才可被重新领取；completed/failed 永不重新领取。
    """
    conn,q = connect()
    with _LOCK:
        run = _locked_run(conn, q, run_id)
        claimed, reason = False, ""
        if run.get("status") == "queued":
            claimed = True
        elif run.get("status") == "running":
            age = age_seconds(run.get("heartbeat_at"), at)
            if recover and (age is None or age >= stale_after):
                claimed = True
                reason = "心跳中断超过%d秒，判定上次计算进程已终止，自动恢复重算" % stale_after
            else:
                reason = "该运行正在其他计算进程中执行，重复投递已忽略"
        else:
            reason = "该运行已处于%s终态，不再重复计算" % run.get("status")
        if not claimed:
            conn.rollback(); conn.close()
            return run, False, reason
        run["status"] = "running"
        run["error"] = ""
        run["last_recovery_error"] = ""
        run["heartbeat_at"] = now_ts()
        attempts = run.setdefault("attempts", [])
        attempts.append({"attempt": attempt_no, "worker_id": worker_id,
                         "started_at": run["heartbeat_at"], "recovered": bool(recover),
                         "recover_reason": reason, "ended_at": "", "outcome": "",
                         "error": ""})
        _commit_run(conn, q, run)
        return run, True, reason

def note_recovery(run_id, error):
    """记录自动恢复的结果；error 为空表示已成功重投。"""
    conn,q = connect()
    with _LOCK:
        run = _locked_run(conn, q, run_id)
        run["last_recovery_error"] = error
        _commit_run(conn, q, run)
        return run

def touch_run(run_id, worker_id, attempt_no, at=None):
    """更新心跳；仅当前 attempt 可写，迟到旧进程的心跳直接拒绝。"""
    conn,q = connect()
    with _LOCK:
        run = _locked_run(conn, q, run_id)
        attempts = run.get("attempts") or []
        if run.get("status") != "running" or not attempts or attempts[-1].get("attempt") != attempt_no \
                or attempts[-1].get("worker_id") != worker_id:
            conn.rollback(); conn.close(); return False
        run["heartbeat_at"] = at or now_ts()
        _commit_run(conn, q, run)
        return True

def finish_run(run_id, worker_id, attempt_no, outcome, result=None, error="", at=None):
    """提交终态。只有当前 attempt 能把运行置为 completed/failed。

    旧进程迟到的结果（attempt 不匹配或运行已终态）会被拒绝，不能覆盖新结果。
    返回 (run, accepted)。
    """
    conn,q = connect()
    with _LOCK:
        run = _locked_run(conn, q, run_id)
        attempts = run.get("attempts") or []
        current = attempts[-1] if attempts else None
        if run.get("status") != "running" or not current \
                or current.get("attempt") != attempt_no or current.get("worker_id") != worker_id:
            conn.rollback(); conn.close()
            return run, False
        stamp = at or now_ts()
        run["status"] = "failed" if outcome == "failed" else "completed"
        run["heartbeat_at"] = stamp
        if outcome == "completed":
            run["result"] = result or {}
            run["error"] = ""
        else:
            run["error"] = error or "计算失败"
        current["ended_at"] = stamp
        current["outcome"] = run["status"]
        current["error"] = run["error"]
        _commit_run(conn, q, run)
        return run, True
