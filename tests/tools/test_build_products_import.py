"""Smoke test for importing tools.build_products."""


def test_tools_import() -> None:
    import tools.build_products as bp

    assert hasattr(bp, "build"), "build_products import failed"
