import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
class ErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try: return await call_next(request)
        except ValueError as exc: return JSONResponse({"detail":str(exc)}, status_code=422)
        except Exception:
            logging.getLogger(__name__).exception("request failed")
            return JSONResponse({"detail":"服务暂时不可用，请重试；中断的计算会在心跳超时后由worker自动恢复，无需重新提交"}, status_code=500)
