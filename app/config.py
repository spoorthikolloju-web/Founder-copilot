import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")  # Gemini API key only

@dataclass
class AgentConfig:
    # Use gemini-2.5-flash-lite as default — lower quota usage, less likely to hit 429.
    # Switch to gemini-2.5-flash in .env for higher quality on paid plans.
    model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
    mcp_server_port: int = 8090
    max_iterations: int = 3
    pii_redaction_enabled: bool = True
    injection_detection_enabled: bool = True

config = AgentConfig()
