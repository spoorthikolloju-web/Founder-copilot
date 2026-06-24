# Root conftest.py — runs before any test collection.
# Sets env vars that prevent live GCP/Vertex AI credential lookups during
# local testing (no Application Default Credentials required).
import os

os.environ.setdefault("SKIP_AGENT_RUNTIME_INIT", "1")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "local-test-project")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")
