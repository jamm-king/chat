"""ASGI entry point. Adapter wiring lives in bootstrap."""
from app.bootstrap import create_app
from app.adapters.inbound.http.api import COOKIE_NAME

app = create_app()
