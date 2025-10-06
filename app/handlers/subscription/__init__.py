"""Subscription-related handlers."""
from . import premium, subscription

routers = (premium.router, subscription.router)

__all__ = ["routers"]
