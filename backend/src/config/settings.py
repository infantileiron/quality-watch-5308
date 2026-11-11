import os
from pathlib import Path
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/quality-watch.sqlite")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
JWT_SECRET = os.getenv("JWT_SECRET", "quality-watch-development-secret-change-this")
SEED_DEMO = os.getenv("SEED_DEMO", "true").lower() == "true"
TASK_MODE = os.getenv("TASK_MODE", "redis")
ARTIFACT_DIR = Path(os.getenv("ARTIFACT_DIR", "/tmp/quality-watch-artifacts"))
# 运行中心跳超过该秒数仍未更新，即判定计算进程中断，可被自动恢复重投
RUN_STALE_SECONDS = int(os.getenv("RUN_STALE_SECONDS", "60"))
# worker 对正在执行的运行刷新心跳的间隔
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "10"))
# worker 扫描中断运行并自动恢复的轮询间隔
RECOVERY_INTERVAL = int(os.getenv("RECOVERY_INTERVAL", "15"))
