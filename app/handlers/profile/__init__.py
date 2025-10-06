"""Profile-related handlers."""
from . import assistant, navigator, notify, picker, reg, report, start

routers = (
    assistant.router,
    navigator.router,
    notify.router,
    picker.router,
    reg.router,
    report.router,
    start.router,
)

__all__ = ["routers"]
