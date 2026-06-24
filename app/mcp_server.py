import os
import sys
import pandas as pd
from fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("founder-copilot-mcp-server")

def _resolve_path(csv_path: str) -> str:
    if not os.path.isabs(csv_path):
        # Try resolving relative to current working directory first
        abs_path = os.path.abspath(csv_path)
        if os.path.exists(abs_path):
            return abs_path
        # Try resolving relative to project root (parent of app directory)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        possible_path = os.path.abspath(os.path.join(project_root, csv_path))
        if os.path.exists(possible_path):
            return possible_path
    return os.path.abspath(csv_path)

@mcp.tool()
def load_startup_metrics(csv_path: str) -> dict:
    """Loads and validates a startup metrics CSV file.

    Args:
        csv_path: Absolute or relative path to the CSV file containing monthly metrics.

    Returns:
        A dictionary containing parsed CSV data or an error message.
    """
    csv_path = _resolve_path(csv_path)
    
    if not os.path.exists(csv_path):
        return {"status": "error", "message": f"File not found: {csv_path}"}
    
    try:
        df = pd.read_csv(csv_path)
        # Required columns validation
        required_cols = {"month", "revenue", "expenses", "cash_on_hand"}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            return {
                "status": "error", 
                "message": f"CSV is missing required columns: {', '.join(missing_cols)}"
            }
        
        # Convert dataframe to dictionary records
        records = df.to_dict(orient="records")
        return {
            "status": "success",
            "columns": list(df.columns),
            "row_count": len(records),
            "data": records
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse CSV: {str(e)}"}

@mcp.tool()
def calculate_financial_metrics(csv_path: str) -> dict:
    """Calculates burn rate, runway, CAC, LTV, and churn from metrics.

    Args:
        csv_path: Absolute path to the startup metrics CSV file.

    Returns:
        A dictionary containing averages and computed financial health metrics.
    """
    csv_path = _resolve_path(csv_path)
    res = load_startup_metrics(csv_path)
    if res["status"] == "error":
        return res
    
    df = pd.read_csv(csv_path)
    
    # Financial metrics averages
    avg_rev = float(df["revenue"].mean())
    avg_exp = float(df["expenses"].mean())
    latest_cash = float(df["cash_on_hand"].iloc[-1])
    
    # Net burn rate
    burn_rate = avg_exp - avg_rev
    
    # Runway estimation
    if burn_rate > 0:
        runway_months = latest_cash / burn_rate
    else:
        runway_months = float("inf")
        
    # Optional columns calculation (SaaS Metrics)
    cac = None
    ltv = None
    churn_rate = None
    
    if "marketing_spend" in df.columns and "new_customers" in df.columns:
        total_marketing = df["marketing_spend"].sum()
        total_new_custs = df["new_customers"].sum()
        if total_new_custs > 0:
            cac = float(total_marketing / total_new_custs)
            
    if "active_users" in df.columns:
        # Simple churn calculation: average drop in active users month-over-month (positive is churn)
        pct_change = df["active_users"].pct_change()
        # Filter where change is negative (loss of users)
        lost_users = pct_change[pct_change < 0]
        if not lost_users.empty:
            churn_rate = float(-lost_users.mean() * 100) # percentage
        else:
            churn_rate = 0.0
            
    # Simple LTV estimation if CAC and Churn are present
    if cac is not None and churn_rate is not None and churn_rate > 0:
        # ARPU (Average Revenue Per User) estimate
        avg_users = df["active_users"].mean()
        if avg_users > 0:
            arpu = avg_rev / avg_users
            ltv = float(arpu / (churn_rate / 100))
            
    return {
        "status": "success",
        "latest_cash_on_hand": latest_cash,
        "average_monthly_revenue": avg_rev,
        "average_monthly_expenses": avg_exp,
        "net_monthly_burn_rate": burn_rate if burn_rate > 0 else 0.0,
        "runway_months": runway_months,
        "cac": cac,
        "estimated_ltv": ltv,
        "ltv_cac_ratio": (ltv / cac) if (ltv is not None and cac is not None and cac > 0) else None,
        "average_churn_rate_pct": churn_rate
    }

@mcp.tool()
def generate_financial_forecast(csv_path: str, growth_rate: float, burn_reduction: float) -> dict:
    """Generates 12-month projections based on growth rate and burn reduction assumptions.

    Args:
        csv_path: Absolute path to the metrics CSV file.
        growth_rate: Target monthly revenue growth rate as a decimal (e.g., 0.10 for 10%).
        burn_reduction: Monthly expenses reduction rate as a decimal (e.g., 0.05 for 5%).

    Returns:
        A dictionary containing projected monthly revenue, expenses, cash, and runway.
    """
    csv_path = _resolve_path(csv_path)
    res = load_startup_metrics(csv_path)
    if res["status"] == "error":
        return res
    
    df = pd.read_csv(csv_path)
    latest_rev = float(df["revenue"].iloc[-1])
    latest_exp = float(df["expenses"].iloc[-1])
    latest_cash = float(df["cash_on_hand"].iloc[-1])
    
    projections = []
    current_cash = latest_cash
    current_rev = latest_rev
    current_exp = latest_exp
    
    for month in range(1, 13):
        # Apply compound growth
        current_rev = current_rev * (1 + growth_rate)
        # Apply expense reduction
        current_exp = current_exp * (1 - burn_reduction)
        # Net cash change
        net_change = current_rev - current_exp
        current_cash += net_change
        
        # Calculate runway at this future point
        future_burn = current_exp - current_rev
        if future_burn > 0:
            future_runway = current_cash / future_burn
        else:
            future_runway = float("inf")
            
        projections.append({
            "month": f"Month +{month}",
            "projected_revenue": round(current_rev, 2),
            "projected_expenses": round(current_exp, 2),
            "projected_cash_on_hand": round(current_cash, 2),
            "projected_burn_rate": round(future_burn if future_burn > 0 else 0.0, 2),
            "projected_runway_months": round(future_runway, 2) if future_runway != float("inf") else "inf"
        })
        
    return {
        "status": "success",
        "growth_rate_assumed": growth_rate,
        "burn_reduction_assumed": burn_reduction,
        "twelve_month_forecast": projections
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
