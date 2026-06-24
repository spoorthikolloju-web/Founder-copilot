# FounderCopilot — Submission Write-Up

## Problem Statement

Startup founders face a critical, recurring challenge: understanding the financial health of their company fast enough to make good decisions. Most founders are not financial analysts — they have spreadsheets of raw metrics but lack the tools to turn those numbers into runway estimates, CAC/LTV ratios, churn rates, and actionable strategies. Hiring analysts is expensive; generic advice tools don't know your specific numbers.

**FounderCopilot** solves this by acting as an always-available AI co-founder that ingests your actual CSV metrics, computes key financial indicators in real time, and delivers investor-ready strategic recommendations — all in a single conversational interaction, protected by a security layer that ensures sensitive data never leaks.

---

## Solution Architecture

```
User Prompt
    │
    ▼
┌──────────────────────┐
│  security_checkpoint │  ◄─ PII scrub + injection detect + audit log
└──────────┬───────────┘
           │ passed / failed
     ┌─────┴──────┐
     │            │
     ▼            ▼
┌──────────┐  ┌─────────────┐
│ security │  │ orchestrator│ ◄─ gemini-3.1-flash-lite
│  _reject │  │   _agent    │
└──────────┘  └──────┬──────┘
                     │  calls tools via MCP
                     ▼
              ┌─────────────────────────────────┐
              │         MCP Server              │
              │  • load_startup_metrics         │
              │  • calculate_financial_metrics  │
              │  • generate_financial_forecast  │
              └─────────────────────────────────┘
                     │
                     ▼
              ┌─────────────┐
              │ final_output│
              └─────────────┘
```

---

## Concepts Used

| Concept | Implementation | File |
|---|---|---|
| **ADK Workflow** | `Workflow(edges=[...])` with `START`, function nodes, and routing | [`app/agent.py`](app/agent.py) |
| **LlmAgent** | `orchestrator_agent` with `gemini-3.1-flash-lite` | [`app/agent.py`](app/agent.py) |
| **MCP Server** | `FastMCP` with 3 domain tools, `stdio` transport | [`app/mcp_server.py`](app/mcp_server.py) |
| **MCPToolset** | Wired into `orchestrator_agent` via `StdioConnectionParams` | [`app/agent.py`](app/agent.py) |
| **Security Checkpoint** | Function node with PII regex, injection keywords, audit log | [`app/agent.py`](app/agent.py) |
| **ctx.state** | `scrubbed_user_prompt` stored in state, injected into agent instruction template | [`app/agent.py`](app/agent.py) |
| **Agents CLI** | Project scaffolded with `agents-cli scaffold create` | `agents-cli-manifest.yaml` |
| **App** | `App(root_agent=root_agent)` exposing the workflow as an ADK app | [`app/agent.py`](app/agent.py) |

---

## Security Design

**Implementation file**: [`app/agent.py`](app/agent.py) — `security_checkpoint()` function node

| Control | Mechanism | Why It Matters |
|---|---|---|
| **PII Scrubbing — Email** | `re.sub(email_pattern, "[REDACTED_EMAIL]", prompt)` | Founders may paste emails; these must never reach the LLM or logs |
| **PII Scrubbing — Phone** | `re.sub(phone_pattern, "[REDACTED_PHONE]", prompt)` | Phone numbers in metrics comments should not be processed |
| **Prompt Injection Detection** | Keyword list: `ignore previous`, `system prompt`, `jailbreak`, `override instructions`, `developer mode` | Prevents adversarial inputs from hijacking the agent's behavior |
| **Domain Content Filter** | Blocks `personal credit card` and `mortgage` queries | Keeps the agent scoped to startup/business finance only |
| **Structured Audit Log** | JSON emitted to `stderr` with `timestamp`, `severity`, `pii_detected`, `injection_detected` | Every decision is traceable — essential for compliance and debugging |

The checkpoint routes clean prompts to `orchestrator_agent` via the `passed` edge; flagged prompts route to `security_reject` via the `failed` edge, which returns a user-facing security alert.

---

## MCP Server Design

**Implementation file**: [`app/mcp_server.py`](app/mcp_server.py)

Built with `FastMCP` using `stdio` transport. The orchestrator agent connects via `McpToolset` + `StdioConnectionParams`.

| Tool | Signature | Purpose |
|---|---|---|
| `load_startup_metrics` | `(csv_path: str) → dict` | Loads and validates the CSV, checks required columns (`month`, `revenue`, `expenses`, `cash_on_hand`) |
| `calculate_financial_metrics` | `(csv_path: str) → dict` | Computes avg revenue, avg expenses, net burn rate, runway months, CAC, LTV, LTV:CAC ratio, churn rate |
| `generate_financial_forecast` | `(csv_path: str, growth_rate: float, burn_reduction: float) → dict` | Generates 12-month compound growth projections with cash-on-hand and runway estimates |

Path resolution logic (`_resolve_path`) automatically handles relative paths — `startup_metrics.csv` resolves relative to the project root, so users don't need to provide absolute paths.

---

## HITL Flow

The current architecture uses **implicit HITL** — the founder states their goals in the initial prompt (e.g., "15% revenue growth, reduce burn by 10%"). This is extracted from `{scrubbed_user_prompt}` injected into the orchestrator's instruction template via `ctx.state`.

A `RequestInput` HITL node (`ask_founder_preferences`) was prototyped and is documented in the codebase history. It was simplified in the final version to eliminate a failure mode where the default fallback value ("general growth and profitability improvement") leaked through as the final output when the orchestrator experienced transient 503 errors during development. The design decision: user intent is already explicit in the prompt — a second interruption adds friction without adding information.

---

## Demo Walkthrough

### Test Case 1 — Metrics Analysis
```
Input: "Analyze my startup metrics from startup_metrics.csv and give me a strategic growth plan. My goal is 10% monthly revenue growth and reduce churn below 5%."
```
Security checkpoint passes. Orchestrator calls `calculate_financial_metrics("startup_metrics.csv")`. Model returns: burn rate ~$3,833/month, runway ~22 months, CAC ~$19, LTV ~$183, LTV:CAC ~9.6x, churn ~0%. Report includes financial health summary, risk analysis, growth strategy, and investor executive summary.

### Test Case 2 — 12-Month Forecast
```
Input: "Generate a 12-month forecast using startup_metrics.csv assuming 15% revenue growth and 5% burn reduction."
```
Orchestrator calls `generate_financial_forecast("startup_metrics.csv", 0.15, 0.05)`. Returns month-by-month projection showing revenue reaching ~$79K+ by month 12, expenses declining, cash-on-hand trajectory.

### Test Case 3 — Security Block
```
Input: "Can you analyze startup_metrics.csv? Also, should I use my personal credit card to fund marketing?"
```
`security_checkpoint` detects "personal credit card" → routes to `security_reject` → playground outputs security alert immediately. No LLM call is made.

---

## Impact & Value Statement

**Who benefits**: Early-stage startup founders (seed to Series A) who need financial clarity without hiring a CFO or analyst.

**How it helps**:
- Replaces hours of manual spreadsheet analysis with a 10-second AI report
- Surfaces critical risks (low runway, high burn, poor LTV:CAC) before they become fatal
- Produces investor-ready language that founders can paste directly into pitch decks
- Security-first design ensures sensitive financial data is scrubbed before reaching any LLM

**Broader impact**: Democratizes access to high-quality financial analysis for the ~90% of founders who cannot afford full-time financial advisors at the early stage.
