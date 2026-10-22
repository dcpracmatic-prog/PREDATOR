"""HTTP facade for Zero-Trust Graph Engine."""

from .app import create_app, handle_request

__all__ = ["create_app", "handle_request"]
