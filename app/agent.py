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

TOOL CALLING RULES — follow exactly:

RULE 1: ALWAYS call calculate_financial_metrics first:
  calculate_financial_metrics(csv_path="startup_metrics.csv")

RULE 2: If the founder mentions ANY percentage, growth rate, reduction, forecast,
  projection, or 12-month in their message, you MUST also call:
  generate_financial_forecast(
      csv_path="startup_metrics.csv",
      growth_rate=<e.g. 0.15 for 15%>,
      burn_reduction=<e.g. 0.05 for 5%, or 0.0 if not stated>
  )

OUTPUT FORMAT — always use these exact sections:

## Financial Health Summary
Show all metrics in a markdown table:
| Metric | Value |
|---|---|
| Avg Monthly Revenue | $X |
| Avg Monthly Expenses | $X |
| Net Burn Rate | $X/month |
| Runway | X months |
| CAC | $X |
| LTV | $X |
| LTV:CAC Ratio | X.Xx |
| Churn Rate | X% |

## Risk Analysis
3 bullet points on critical findings from the numbers.

## Growth Strategy and Recommendations
3-5 specific actionable steps based on the actual metrics and the founder's goals.

## Investor Executive Summary
3-5 polished sentences for a pitch deck.

## 12-Month Financial Forecast
ONLY include this section if you called generate_financial_forecast.
Format twelve_month_forecast as a markdown table with ALL 12 rows:
| Month | Proj. Revenue | Proj. Expenses | Cash on Hand | Burn Rate | Runway (mo) |
|---|---|---|---|---|---|
| Month +1 | $X | $X | $X | $X | X |
(continue for all 12 months)

Use real numbers from the tools only. Never invent figures.
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

