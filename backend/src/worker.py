import logging
import time
from pathlib import Path

import redis

from src.config.settings import REDIS_URL, RECOVERY_INTERVAL
from src.services import run as run_service
from src.utils.repository import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("worker")
HEARTBEAT_FILE = Path("/tmp/worker-heartbeat")


def main():
    init_db()
    client = redis.Redis.from_url(REDIS_URL)
    worker_id = run_service.worker_identity()
    last_sweep = 0.0
    logger.info("worker 启动 %s", worker_id)
    while True:
        HEARTBEAT_FILE.write_text(str(time.time()))
        now_ts = time.time()
        if now_ts - last_sweep >= RECOVERY_INTERVAL:
            last_sweep = now_ts
            try:
                run_service.recover_stale(client, worker_id)
            except Exception:
                logger.exception("中断运行恢复扫描失败")
        try:
            item = client.blpop(run_service.JOB_QUEUE, timeout=3)
            if item:
                run_id = item[1].decode()
                logger.info("领取运行 %s", run_id)
                # recover=True：排队任务正常领取；崩溃中断的运行自动恢复；
                # 重复投递和并发领取在事务状态机里被判定忽略。
                run_service.execute(run_id, worker_id=worker_id, recover=True)
        except Exception:
            logger.exception("worker 主循环异常")
            time.sleep(2)


if __name__ == "__main__":
    main()
