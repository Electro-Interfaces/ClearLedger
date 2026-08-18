import inspect

from app.routers import store_router


def test_catalog_health_counts_only_live_items():
    source = inspect.getsource(store_router.catalog_health)
    assert "b.status = 'rejected' AND NOT i.deleted" in source
    assert "e.resolved_at IS NULL AND NOT i.deleted" in source


def test_enrichment_total_matches_visible_live_rows():
    source = inspect.getsource(store_router.catalog_enrichment)
    assert source.count("NOT i.deleted") == 2
