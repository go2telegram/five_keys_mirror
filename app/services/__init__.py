"""Service layer helpers."""

__all__ = ["catalog_search", "product_get", "get_reco"]


def __getattr__(name: str):  # pragma: no cover - compatibility shim
    if name in __all__:
        from . import catalog_service

        return getattr(catalog_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
