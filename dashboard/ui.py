"""
Micro Mean Revert Strategy Dashboard.

Custom dashboard showing RSI indicator, circuit breaker status,
micro-wallet position, trade history, and performance metrics.
"""

from decimal import Decimal
from typing import Any

import streamlit as st


def render_custom_dashboard(
    strategy_id: str,
    strategy_config: dict[str, Any],
    api_client: Any,
    session_state: dict[str, Any],
) -> None:
    """Render the Micro Mean Revert custom dashboard."""
    st.title("Micro Mean Revert Dashboard")

    # Extract config values
    base_token = strategy_config.get("base_token", "WETH")
    quote_token = strategy_config.get("quote_token", "USDC")
    rsi_period = int(strategy_config.get("rsi_period", 7))
    rsi_timeframe = strategy_config.get("rsi_timeframe", "1m")
    rsi_oversold = Decimal(str(strategy_config.get("rsi_oversold", "30")))
    rsi_overbought = Decimal(str(strategy_config.get("rsi_overbought", "70")))
    trade_pct = Decimal(str(strategy_config.get("trade_pct", "0.20")))
    max_slippage_bps = int(strategy_config.get("max_slippage_bps", 100))
    max_failures = int(strategy_config.get("max_consecutive_failures", 3))
    cooldown_secs = int(strategy_config.get("failure_cooldown_seconds", 300))

    # Header info
    col_id, col_pair, col_chain = st.columns(3)
    with col_id:
        st.markdown(f"**Strategy ID:** `{strategy_id[:12]}...`")
    with col_pair:
        st.markdown(f"**Pair:** {base_token}/{quote_token}")
    with col_chain:
        st.markdown(f"**Chain:** Arbitrum | **DEX:** Uniswap V3")

    st.divider()

    # ── RSI Indicator ──────────────────────────────────────────────
    st.subheader(f"RSI({rsi_period}, {rsi_timeframe})")
    _render_rsi_section(session_state, rsi_period, rsi_timeframe, rsi_oversold, rsi_overbought, base_token)

    st.divider()

    # ── Circuit Breaker ────────────────────────────────────────────
    st.subheader("Circuit Breaker")
    _render_circuit_breaker(session_state, max_failures, cooldown_secs)

    st.divider()

    # ── Position ───────────────────────────────────────────────────
    st.subheader("Micro Wallet Position")
    _render_position(session_state, base_token, quote_token, trade_pct, max_slippage_bps)

    st.divider()

    # ── Trade History ──────────────────────────────────────────────
    st.subheader("Recent Trades")
    _render_trade_history(api_client)

    st.divider()

    # ── Performance ────────────────────────────────────────────────
    st.subheader("Performance")
    _render_performance(session_state)


# ── Section renderers ──────────────────────────────────────────────


def _render_rsi_section(
    session_state: dict[str, Any],
    rsi_period: int,
    rsi_timeframe: str,
    rsi_oversold: Decimal,
    rsi_overbought: Decimal,
    base_token: str,
) -> None:
    """Render RSI indicator with zone coloring and progress gauge."""
    current_rsi = Decimal(str(session_state.get("current_rsi", session_state.get("rsi_value", "50"))))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            f"RSI({rsi_period})",
            f"{float(current_rsi):.1f}",
            help=f"RSI on {rsi_timeframe} timeframe (0-100)",
        )
    with col2:
        st.metric("Oversold", f"{float(rsi_oversold):.0f}", help="Buy when RSI drops below")
    with col3:
        st.metric("Overbought", f"{float(rsi_overbought):.0f}", help="Sell when RSI rises above")

    # Zone indicator
    if current_rsi <= rsi_oversold:
        st.success(f"OVERSOLD - Buy {base_token} signal (RSI {float(current_rsi):.1f})")
    elif current_rsi >= rsi_overbought:
        st.error(f"OVERBOUGHT - Sell {base_token} signal (RSI {float(current_rsi):.1f})")
    else:
        st.info(f"NEUTRAL - Holding (RSI {float(current_rsi):.1f})")

    # Gauge bar
    col_bar, col_label = st.columns([4, 1])
    with col_bar:
        st.progress(max(0.0, min(1.0, float(current_rsi) / 100)))
    with col_label:
        st.markdown(f"**{float(current_rsi):.0f}/100**")


def _render_circuit_breaker(
    session_state: dict[str, Any],
    max_failures: int,
    cooldown_secs: int,
) -> None:
    """Render circuit breaker status."""
    consecutive_failures = int(session_state.get("consecutive_failures", 0))
    cooldown_until = float(session_state.get("failure_cooldown_until", 0))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "Consecutive Failures",
            f"{consecutive_failures}/{max_failures}",
            help="Strategy pauses after hitting max failures",
        )
    with col2:
        st.metric("Max Failures", str(max_failures))
    with col3:
        st.metric("Cooldown", f"{cooldown_secs}s", help="Cooldown duration after circuit break")

    # Status
    import time

    now = time.time()
    if cooldown_until > now:
        remaining = int(cooldown_until - now)
        st.warning(f"CIRCUIT BREAKER ACTIVE - Cooldown: {remaining}s remaining")
    elif consecutive_failures > 0:
        st.warning(f"Failures building: {consecutive_failures}/{max_failures}")
    else:
        st.success("Circuit breaker OK - No recent failures")


def _render_position(
    session_state: dict[str, Any],
    base_token: str,
    quote_token: str,
    trade_pct: Decimal,
    max_slippage_bps: int,
) -> None:
    """Render micro-wallet position and sizing info."""
    base_balance = Decimal(str(session_state.get("base_balance", "0")))
    quote_balance = Decimal(str(session_state.get("quote_balance", "0")))
    base_price = Decimal(str(session_state.get("base_price", "0")))

    base_usd = base_balance * base_price if base_price > 0 else Decimal("0")
    total_value = base_usd + quote_balance

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(f"{base_token}", f"{float(base_balance):.6f}", help=f"~${float(base_usd):.4f}")
    with col2:
        st.metric(f"{quote_token}", f"${float(quote_balance):.4f}")
    with col3:
        st.metric("Total Value", f"${float(total_value):.4f}")
    with col4:
        next_trade = total_value * trade_pct
        st.metric("Next Trade Size", f"${float(next_trade):.4f}", help=f"{float(trade_pct)*100:.0f}% allocation")

    # Allocation bar
    if total_value > 0:
        base_pct = float(base_usd / total_value * 100)
        quote_pct = float(quote_balance / total_value * 100)
        st.markdown(
            f"**Allocation:** {base_pct:.0f}% {base_token} | {quote_pct:.0f}% {quote_token} "
            f"&nbsp;&bull;&nbsp; **Slippage limit:** {max_slippage_bps} bps"
        )


def _render_trade_history(api_client: Any) -> None:
    """Render recent swap history from the timeline."""
    trades: list[dict[str, Any]] = []
    if api_client:
        try:
            events = api_client.get_timeline(limit=20)
            trades = [e for e in events if e.get("event_type") in ("SWAP", "swap")]
        except Exception:
            pass

    if trades:
        for trade in trades[:8]:
            ts = trade.get("timestamp", "")
            ts_short = ts[:19] if ts and len(ts) > 19 else ts
            details = trade.get("details", {})
            from_tok = details.get("from_token", "?")
            to_tok = details.get("to_token", "?")
            amount = details.get("amount", "")
            tx = trade.get("tx_hash", "")
            tx_short = f" `{tx[:10]}...`" if tx else ""

            amount_str = f" ({amount})" if amount else ""
            st.markdown(f"- `{ts_short}` {from_tok} -> {to_tok}{amount_str}{tx_short}")
    else:
        st.info("No trades yet. Strategy executes when RSI crosses oversold/overbought thresholds.")


def _render_performance(session_state: dict[str, Any]) -> None:
    """Render PnL and trade metrics."""
    total_pnl = Decimal(str(session_state.get("total_pnl", "0")))
    total_trades = int(session_state.get("total_trades", 0))
    win_rate = Decimal(str(session_state.get("win_rate", "0")))
    avg_trade = total_pnl / Decimal(str(total_trades)) if total_trades > 0 else Decimal("0")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        sign = "+" if total_pnl >= 0 else ""
        st.metric("Total PnL", f"{sign}${float(abs(total_pnl)):,.4f}")
    with col2:
        st.metric("Total Trades", str(total_trades))
    with col3:
        st.metric("Win Rate", f"{float(win_rate):.0f}%")
    with col4:
        st.metric("Avg Trade", f"${float(avg_trade):+,.4f}")

    if total_pnl > 0:
        st.success(f"Profitable: +${float(total_pnl):,.4f}")
    elif total_pnl < 0:
        st.warning(f"At a loss: ${float(total_pnl):,.4f}")
    elif total_trades == 0:
        st.info("No trades executed yet.")
    else:
        st.info("Breakeven.")
