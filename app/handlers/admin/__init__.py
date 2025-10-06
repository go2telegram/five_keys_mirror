"""Admin area handlers."""
from . import commands

routers = (commands.router,)

__all__ = ["routers"]
