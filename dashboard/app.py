"""
Micro Mean Revert — Standalone Dashboard

Focused dashboard for the micro mean revert strategy only.
Run with: streamlit run dashboard/app.py
"""

import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STRATEGY_NAME = "MicroMeanRevertStrategy"
REFRESH_INTERVAL = 10  # seconds
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "50051"))

# Load strategy config.json
_config_path = Path(__file__).parent.parent / "config.json"
if _config_path.exists():
    STRATEGY_CONFIG = json.loads(_config_path.read_text())
else:
    STRATEGY_CONFIG = {}

BASE_TOKEN = STRATEGY_CONFIG.get("base_token", "WETH")
QUOTE_TOKEN = STRATEGY_CONFIG.get("quote_token", "USDC")
RSI_PERIOD = int(STRATEGY_CONFIG.get("rsi_period", 3))
RSI_TIMEFRAME = STRATEGY_CONFIG.get("rsi_timeframe", "1m")
RSI_OVERSOLD = float(STRATEGY_CONFIG.get("rsi_oversold", 48))
RSI_OVERBOUGHT = float(STRATEGY_CONFIG.get("rsi_overbought", 52))
TRADE_PCT = float(STRATEGY_CONFIG.get("trade_pct", 0.20))
MAX_SLIPPAGE_BPS = int(STRATEGY_CONFIG.get("max_slippage_bps", 100))
MAX_FAILURES = int(STRATEGY_CONFIG.get("max_consecutive_failures", 3))
COOLDOWN_SECS = int(STRATEGY_CONFIG.get("failure_cooldown_seconds", 300))


# ---------------------------------------------------------------------------
# Gateway helpers
# ---------------------------------------------------------------------------


def _get_client():
    """Get a connected GatewayDashboardClient."""
    from almanak.framework.dashboard.gateway_client import GatewayDashboardClient
    from almanak.framework.gateway_client import GatewayClient, GatewayClientConfig

    config = GatewayClientConfig(host=GATEWAY_HOST, port=GATEWAY_PORT, auth_token=None)
    gw = GatewayClient(config)
    gw.connect()
    return GatewayDashboardClient(gateway_client=gw)


@st.cache_data(ttl=REFRESH_INTERVAL)
def _fetch_strategies():
    """Return list of StrategySummary from gateway (cached)."""
    try:
        client = _get_client()
        client.connect()
        return client.list_strategies(include_position=True)
    except Exception as e:
        st.error(f"Gateway error: {e}")
        return []


def _fetch_details(strategy_id: str):
    """Fetch full StrategyDetails for a given id."""
    try:
        client = _get_client()
        client.connect()
        return client.get_strategy_details(
            strategy_id, include_timeline=True, include_pnl_history=True, timeline_limit=100
        )
    except Exception:
        return None


def _fetch_timeline(strategy_id: str, limit: int = 100):
    """Fetch timeline events."""
    try:
        client = _get_client()
        client.connect()
        return client.get_timeline(strategy_id, limit=limit)
    except Exception:
        return []


def _fetch_state(strategy_id: str):
    """Fetch strategy state dict."""
    try:
        client = _get_client()
        client.connect()
        return client.get_strategy_state(strategy_id)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Session-state history accumulators
# ---------------------------------------------------------------------------


def _append_history(key: str, value: float, max_len: int = 300):
    """Append a timestamped value to session_state history list."""
    if key not in st.session_state:
        st.session_state[key] = []
    st.session_state[key].append({"t": datetime.now(tz=UTC), "v": value})
    if len(st.session_state[key]) > max_len:
        st.session_state[key] = st.session_state[key][-max_len:]


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------


def _rsi_chart(history: list[dict]) -> go.Figure:
    """Build RSI time-series chart with oversold/overbought bands."""
    ts = [h["t"] for h in history]
    vals = [h["v"] for h in history]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ts, y=vals, mode="lines+markers", name="RSI",
        line=dict(color="#5B8DEF", width=2),
        marker=dict(size=4),
    ))
    # Bands
    fig.add_hline(y=RSI_OVERSOLD, line_dash="dash", line_color="#22c55e",
                  annotation_text=f"Oversold ({RSI_OVERSOLD})")
    fig.add_hline(y=RSI_OVERBOUGHT, line_dash="dash", line_color="#ef4444",
                  annotation_text=f"Overbought ({RSI_OVERBOUGHT})")
    # Shading
    fig.add_hrect(y0=0, y1=RSI_OVERSOLD, fillcolor="#22c55e", opacity=0.07, line_width=0)
    fig.add_hrect(y0=RSI_OVERBOUGHT, y1=100, fillcolor="#ef4444", opacity=0.07, line_width=0)

    fig.update_layout(
        yaxis=dict(range=[0, 100], title="RSI"),
        xaxis=dict(title=""),
        margin=dict(l=40, r=20, t=10, b=30),
        height=260,
        showlegend=False,
    )
    return fig


def _portfolio_chart(history: list[dict]) -> go.Figure:
    """Portfolio value over time."""
    ts = [h["t"] for h in history]
    vals = [h["v"] for h in history]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ts, y=vals, mode="lines", name="Portfolio USD",
        fill="tozeroy", fillcolor="rgba(91,141,239,0.15)",
        line=dict(color="#5B8DEF", width=2),
    ))
    fig.update_layout(
        yaxis=dict(title="USD", tickprefix="$"),
        xaxis=dict(title=""),
        margin=dict(l=50, r=20, t=10, b=30),
        height=220,
        showlegend=False,
    )
    return fig


def _allocation_chart(base_usd: float, quote_usd: float) -> go.Figure:
    """Donut chart of portfolio allocation."""
    fig = go.Figure(go.Pie(
        labels=[BASE_TOKEN, QUOTE_TOKEN],
        values=[max(base_usd, 0), max(quote_usd, 0)],
        hole=0.55,
        marker=dict(colors=["#5B8DEF", "#22c55e"]),
        textinfo="label+percent",
        textposition="outside",
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=220,
        showlegend=False,
    )
    return fig


def _trade_chart(trades: list[dict], price_history: list[dict]) -> go.Figure:
    """Price chart with buy/sell markers overlaid."""
    fig = go.Figure()

    # Price line (if we have history)
    if price_history:
        ts = [h["t"] for h in price_history]
        vals = [h["v"] for h in price_history]
        fig.add_trace(go.Scatter(
            x=ts, y=vals, mode="lines", name=f"{BASE_TOKEN} Price",
            line=dict(color="#94a3b8", width=1.5),
        ))

    # Buy markers
    buys = [t for t in trades if t.get("side") == "BUY"]
    if buys:
        fig.add_trace(go.Scatter(
            x=[b["t"] for b in buys],
            y=[b["price"] for b in buys],
            mode="markers", name="BUY",
            marker=dict(color="#22c55e", size=10, symbol="triangle-up"),
        ))

    # Sell markers
    sells = [t for t in trades if t.get("side") == "SELL"]
    if sells:
        fig.add_trace(go.Scatter(
            x=[s["t"] for s in sells],
            y=[s["price"] for s in sells],
            mode="markers", name="SELL",
            marker=dict(color="#ef4444", size=10, symbol="triangle-down"),
        ))

    fig.update_layout(
        yaxis=dict(title="Price (USD)", tickprefix="$"),
        xaxis=dict(title=""),
        margin=dict(l=50, r=20, t=10, b=30),
        height=260,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


# ---------------------------------------------------------------------------
# Page renderer
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(
        page_title=f"Micro Mean Revert | {BASE_TOKEN}/{QUOTE_TOKEN}",
        page_icon="📉",
        layout="wide",
    )

    # ── CSS tweaks ──
    st.markdown("""
    <style>
    [data-testid="stMetric"] { padding: 8px 12px; }
    .block-container { padding-top: 1.5rem; }
    </style>
    """, unsafe_allow_html=True)

    # ── Header ──
    hdr1, hdr2, hdr3 = st.columns([4, 1, 1])
    with hdr1:
        st.markdown(f"# 📉 Micro Mean Revert &nbsp;|&nbsp; {BASE_TOKEN}/{QUOTE_TOKEN}")
        st.caption(f"Arbitrum · Uniswap V3 · RSI({RSI_PERIOD}, {RSI_TIMEFRAME}) · {TRADE_PCT*100:.0f}% sizing")
    with hdr2:
        auto = st.toggle("Auto-refresh", value=True)
    with hdr3:
        if st.button("Refresh"):
            _fetch_strategies.clear()
            st.rerun()

    # ── Find our strategy ──
    summaries = _fetch_strategies()
    my_strats = [
        s for s in summaries
        if STRATEGY_NAME.lower() in s.name.lower() or STRATEGY_NAME in s.strategy_id
    ]
    # Prefer RUNNING instances, then most recent
    my_strats.sort(key=lambda s: (s.status != "RUNNING", s.strategy_id), reverse=False)

    if not my_strats:
        st.warning(
            f"No running **{STRATEGY_NAME}** instance found in the gateway. "
            "Make sure the strategy is running with `almanak strat run`."
        )
        st.stop()

    strat = my_strats[0]  # use first match
    strategy_id = strat.strategy_id

    # Fetch details + state
    details = _fetch_details(strategy_id)
    state = _fetch_state(strategy_id)
    timeline = _fetch_timeline(strategy_id, limit=100)

    # ── Parse live values ──
    base_bal = Decimal("0")
    base_usd = Decimal("0")
    quote_bal = Decimal("0")
    quote_usd = Decimal("0")
    if details and details.position:
        for tb in details.position.token_balances:
            if tb.symbol == BASE_TOKEN:
                base_bal = tb.balance
                base_usd = tb.value_usd
            elif tb.symbol == QUOTE_TOKEN:
                quote_bal = tb.balance
                quote_usd = tb.value_usd

    total_usd = float(base_usd + quote_usd)
    base_price = float(base_usd / base_bal) if base_bal > 0 else 0

    # RSI from state
    current_rsi = float(state.get("current_rsi", state.get("rsi_value", 50)))
    consecutive_failures = int(state.get("consecutive_failures", 0))
    cooldown_until = float(state.get("failure_cooldown_until", 0))

    # Accumulate history
    _append_history("rsi_history", current_rsi)
    _append_history("portfolio_history", total_usd)
    if base_price > 0:
        _append_history("price_history", base_price)

    # Parse trades from timeline
    trades_parsed: list[dict] = []
    if timeline:
        for ev in timeline:
            if ev.event_type.upper() in ("SWAP", "TRADE", "TRANSACTION_CONFIRMED"):
                d = ev.details or {}
                from_tok = d.get("from_token", d.get("intent_from_token", ""))
                to_tok = d.get("to_token", d.get("intent_to_token", ""))
                side = "BUY" if to_tok == BASE_TOKEN else "SELL" if from_tok == BASE_TOKEN else ""
                trades_parsed.append({
                    "t": ev.timestamp or datetime.now(tz=UTC),
                    "side": side,
                    "from": from_tok,
                    "to": to_tok,
                    "price": base_price,
                    "amount": d.get("amount", d.get("intent_amount_usd", "")),
                    "tx": ev.tx_hash or "",
                    "desc": ev.description,
                })

    # ================================================================
    # LAYOUT
    # ================================================================

    # ── Row 1: Key metrics ──
    st.divider()
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        rsi_delta = None
        rsi_hist = st.session_state.get("rsi_history", [])
        if len(rsi_hist) >= 2:
            rsi_delta = f"{rsi_hist[-1]['v'] - rsi_hist[-2]['v']:+.1f}"
        st.metric(f"RSI({RSI_PERIOD})", f"{current_rsi:.1f}", delta=rsi_delta)
    with m2:
        st.metric("Status", strat.status)
    with m3:
        st.metric("Portfolio", f"${total_usd:.4f}")
    with m4:
        st.metric(BASE_TOKEN, f"{float(base_bal):.6f}")
    with m5:
        st.metric(QUOTE_TOKEN, f"${float(quote_usd):.4f}")
    with m6:
        trade_size = total_usd * TRADE_PCT
        st.metric("Trade Size", f"${trade_size:.4f}")

    # ── Row 2: RSI chart + Allocation ──
    st.divider()
    chart_col1, chart_col2 = st.columns([3, 1])

    with chart_col1:
        st.markdown(f"**RSI({RSI_PERIOD}, {RSI_TIMEFRAME})**")
        rsi_hist = st.session_state.get("rsi_history", [])
        if len(rsi_hist) >= 2:
            st.plotly_chart(_rsi_chart(rsi_hist), use_container_width=True, key="rsi_chart")
        else:
            st.info("Accumulating RSI data... (will chart after 2+ data points)")

        # Signal indicator
        if current_rsi <= RSI_OVERSOLD:
            st.success(f"OVERSOLD — Buy {BASE_TOKEN} (RSI {current_rsi:.1f} < {RSI_OVERSOLD})")
        elif current_rsi >= RSI_OVERBOUGHT:
            st.error(f"OVERBOUGHT — Sell {BASE_TOKEN} (RSI {current_rsi:.1f} > {RSI_OVERBOUGHT})")
        else:
            st.info(f"NEUTRAL — Holding (RSI {current_rsi:.1f})")

    with chart_col2:
        st.markdown("**Allocation**")
        if total_usd > 0:
            st.plotly_chart(
                _allocation_chart(float(base_usd), float(quote_usd)),
                use_container_width=True,
                key="alloc_chart",
            )
        else:
            st.caption("No funds")

        # Circuit breaker compact
        st.markdown("**Circuit Breaker**")
        now = time.time()
        if cooldown_until > now:
            remaining = int(cooldown_until - now)
            st.warning(f"ACTIVE — {remaining}s left")
        elif consecutive_failures > 0:
            st.warning(f"Failures: {consecutive_failures}/{MAX_FAILURES}")
        else:
            st.success("OK")

    # ── Row 3: Portfolio chart + Trade chart ──
    st.divider()
    pc1, pc2 = st.columns(2)

    with pc1:
        st.markdown("**Portfolio Value**")
        port_hist = st.session_state.get("portfolio_history", [])
        if len(port_hist) >= 2:
            st.plotly_chart(_portfolio_chart(port_hist), use_container_width=True, key="port_chart")
        else:
            st.info("Accumulating data...")

    with pc2:
        st.markdown(f"**{BASE_TOKEN} Price & Trades**")
        price_hist = st.session_state.get("price_history", [])
        if len(price_hist) >= 2 or trades_parsed:
            st.plotly_chart(
                _trade_chart(trades_parsed, price_hist),
                use_container_width=True,
                key="trade_chart",
            )
        else:
            st.info("Accumulating data...")

    # ── Row 4: Trade history table ──
    st.divider()
    st.markdown("**Recent Trades**")
    if trades_parsed:
        for t in trades_parsed[:15]:
            ts = t["t"].strftime("%H:%M:%S") if t["t"] else ""
            icon = "🟢" if t["side"] == "BUY" else "🔴" if t["side"] == "SELL" else "⚪"
            amt = f" ${t['amount']}" if t["amount"] else ""
            tx = f" `{t['tx'][:10]}…`" if t["tx"] else ""
            st.markdown(f"{icon} `{ts}` **{t['side']}** {t['from']} → {t['to']}{amt}{tx}")
    else:
        st.caption("No trades yet. Waiting for RSI to cross oversold/overbought thresholds.")

    # ── Row 5: Config ──
    with st.expander("Strategy Config"):
        cfg1, cfg2, cfg3 = st.columns(3)
        with cfg1:
            st.markdown(f"**Pair:** {BASE_TOKEN}/{QUOTE_TOKEN}")
            st.markdown(f"**RSI Period:** {RSI_PERIOD}")
            st.markdown(f"**RSI Timeframe:** {RSI_TIMEFRAME}")
        with cfg2:
            st.markdown(f"**Oversold:** {RSI_OVERSOLD}")
            st.markdown(f"**Overbought:** {RSI_OVERBOUGHT}")
            st.markdown(f"**Trade %:** {TRADE_PCT*100:.0f}%")
        with cfg3:
            st.markdown(f"**Max Slippage:** {MAX_SLIPPAGE_BPS} bps")
            st.markdown(f"**Max Failures:** {MAX_FAILURES}")
            st.markdown(f"**Cooldown:** {COOLDOWN_SECS}s")
        st.markdown(f"**Instance ID:** `{strategy_id}`")

    # ── Footer ──
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')} · Gateway: {GATEWAY_HOST}:{GATEWAY_PORT}")

    # Auto-refresh
    if auto:
        time.sleep(REFRESH_INTERVAL)
        _fetch_strategies.clear()
        st.rerun()


if __name__ == "__main__":
    main()
