from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Checks the X-API-Key header on every incoming request.
    Returns 401 if the header is missing or does not match the configured key.
    Returns 503 if the app is still in the startup phase (config not yet loaded).
    """

    # Paths that bypass API-key auth entirely
    _PUBLIC_PATHS = {"/health"}

    async def dispatch(self, request: Request, call_next):
        # /health is public  no key required (Docker healthcheck, load balancers)
        if request.url.path in self._PUBLIC_PATHS:
            return await call_next(request)

        # Guard: config is loaded during lifespan; reject requests that arrive
        # before startup completes (edge case during slow DB connection checks).
        if not hasattr(request.app.state, "config"):
            return JSONResponse(
                {"detail": "Service is starting up, please retry shortly"},
                status_code=503,
            )

        # /logs/stream also accepts ?api_key= (EventSource can't set headers);
        # that secondary check is handled inside the route itself.
        api_key = request.headers.get("X-API-Key")

        # Allow SSE clients that pass api_key as query param instead of header
        if api_key is None and request.url.path == "/logs/stream":
            api_key = request.query_params.get("api_key")

        expected_key = request.app.state.config.api.api_key

        if api_key != expected_key:
            return JSONResponse(
                {"detail": "Unauthorized: missing or invalid X-API-Key header"},
                status_code=401,
            )

        return await call_next(request)
