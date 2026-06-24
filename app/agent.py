import os
import re
import sys
import json
import datetime
from zoneinfo import ZoneInfo
from typing import Any

from google.adk.workflow import Workflow, START
from google.adk.agents import LlmAgent
from google.adk.events.event import Event
from google.adk.agents.context import Context
from google.adk.apps import App
from google.genai import types

from .config import config

# Initialize MCP Toolset — gives the orchestrator direct access to all 3 MCP tools
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

mcp_server_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_server.py"))

mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[mcp_server_path],
        )
    )
)

# ── Single orchestrator agent (1 LLM call) ─────────────────────────────────
orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    model=config.model,
    instruction="""You are FounderCopilot — an expert AI advisor for startup founders.

The founder said: {scrubbed_user_prompt}

You have access to these tools:
1. calculate_financial_metrics(csv_path) — computes burn rate, runway, CAC, LTV, churn
2. load_startup_metrics(csv_path) — loads and validates the CSV
3. generate_financial_forecast(csv_path, growth_rate, burn_reduction) — 12-month projections

STEP 1: Always start by calling calculate_financial_metrics with csv_path="startup_metrics.csv"

STEP 2: If the founder mentions a growth rate target (e.g. "10% monthly growth"), also call generate_financial_forecast with the appropriate growth_rate and burn_reduction values.

STEP 3: Write a comprehensive founder report using ALL the data returned:

## 📊 Financial Health Summary
(Actual numbers: revenue trend, expenses, burn rate, runway months, CAC, LTV, LTV:CAC ratio, churn)

## 🔥 Risk Analysis
(What the numbers reveal — highlight any critical thresholds like runway < 12 months)

## 🚀 Growth Strategy & Recommendations
(Specific, actionable steps based on the founder's stated goals and the actual metrics)

## 📈 Investor Executive Summary
(3-5 sentences, polished enough to paste into a deck)

Always be specific — use the actual numbers from the tools, not generic advice.
""",
    tools=[mcp_toolset]
)

# ── Node 1: Security Checkpoint (pure Python — no LLM call) ────────────────
def security_checkpoint(ctx: Context, node_input: Any):
    # Extract prompt text
    prompt = ""
    if hasattr(node_input, "parts") and node_input.parts:
        prompt = "".join([p.text for p in node_input.parts if p.text])
    elif isinstance(node_input, str):
        prompt = node_input

    # Prompt injection check
    is_injection = False
    injection_keywords = [
        "ignore previous", "system prompt", "jailbreak",
        "override instructions", "developer mode"
    ]
    for keyword in injection_keywords:
        if keyword in prompt.lower():
            is_injection = True
            break

    # PII scrubbing
    scrubbed_prompt = prompt
    email_pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    phone_pattern = r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"

    pii_found = False
    if re.search(email_pattern, prompt):
        scrubbed_prompt = re.sub(email_pattern, "[REDACTED_EMAIL]", scrubbed_prompt)
        pii_found = True
    if re.search(phone_pattern, prompt):
        scrubbed_prompt = re.sub(phone_pattern, "[REDACTED_PHONE]", scrubbed_prompt)
        pii_found = True

    # Domain-specific content filter
    if "personal credit card" in prompt.lower() or "mortgage" in prompt.lower():
        is_injection = True

    # Structured JSON audit log
    audit_log = {
        "timestamp": datetime.datetime.now(ZoneInfo("UTC")).isoformat(),
        "severity": "CRITICAL" if is_injection else ("WARNING" if pii_found else "INFO"),
        "event": "security_checkpoint_evaluation",
        "pii_detected": pii_found,
        "injection_detected": is_injection,
        "original_length": len(prompt),
        "scrubbed_length": len(scrubbed_prompt)
    }
    print(f"AUDIT_LOG: {json.dumps(audit_log)}", file=sys.stderr)

    if is_injection:
        return Event(output="Security Check Failed", route="failed")

    return Event(
        output=scrubbed_prompt,
        route="passed",
        state={"scrubbed_user_prompt": scrubbed_prompt},
    )

# ── Node 2: Security Reject (async — required for multi-yield nodes) ─────────
async def security_reject(ctx: Context, node_input: Any):
    yield Event(content=types.Content(
        role="model",
        parts=[types.Part.from_text(
            text="⚠️ Security Alert: Prompt rejected due to policy violations (PII or injection detected)."
        )]
    ))
    yield Event(output="Security Check Failed")

# ── Node 3: Final Output (async — required for yield nodes) ─────────────────
async def final_output(ctx: Context, node_input: Any):
    yield Event(output=node_input)

# ── Workflow: security → orchestrator → final output ────────────────────────
# Removed ask_founder_preferences HITL node — its fallback value was leaking
# through as the visible output when the orchestrator hit transient 503 errors.
# The orchestrator already receives the full user prompt via {scrubbed_user_prompt}.
root_agent = Workflow(
    name="founder_copilot_workflow",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {"passed": orchestrator_agent, "failed": security_reject}),
        (orchestrator_agent, final_output)
    ]
)

app = App(
    root_agent=root_agent,
    name="app",
)
