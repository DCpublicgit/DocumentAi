from app.config import settings

# TestClient(app) (tests/test_server.py) runs the real FastAPI lifespan,
# including startup model warm-up. Off in tests: it costs ~150s cold on the
# CPU-only pilot VM and every other test file mocks or skips the real
# BGE-M3/reranker models entirely (see tests/test_reranker.py) — the test
# suite has never depended on the actual weights being loaded.
settings.warm_up_models_enabled = False
