"""Bound request bytes before multipart parsing can spool arbitrary uploads."""
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from app.config import settings


class RequestTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, "Файл или запрос превышает допустимый размер")


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return
        maximum = settings.upload_max_bytes + 65536
        headers = dict(scope.get("headers", []))
        if b"content-length" in headers:
            try:
                length = int(headers[b"content-length"])
                if length < 0:
                    raise ValueError
            except ValueError:
                await JSONResponse({"detail": "Недопустимый размер запроса"}, status_code=400)(scope, receive, send)
                return
            if length > maximum:
                await JSONResponse({"detail": "Файл или запрос превышает допустимый размер"}, status_code=413)(scope, receive, send)
                return
        received, started = 0, False

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    raise RequestTooLarge
            return message

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracked_send)
        except RequestTooLarge:
            if started:
                raise
            await JSONResponse({"detail": "Файл или запрос превышает допустимый размер"}, status_code=413)(scope, receive, send)
