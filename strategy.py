"""
Micro Mean Reversion Strategy

RSI-based mean reversion on very short timeframes (<1 min).
Sized for a tiny wallet (~$1) with 20% per-trade allocation.

Chain: Arbitrum
"""

import logging
import time
from decimal import Decimal
from typing import Any, Optional

from almanak.framework.strategies import (
    IntentStrategy,
    MarketSnapshot,
    almanak_strategy,
)
from almanak.framework.intents import Intent

logger = logging.getLogger(__name__)


@almanak_strategy(
    name="micro_mean_revert",
    description="Sub-minute RSI mean reversion for micro-sized wallets",
    version="1.0.0",
    supported_chains=["arbitrum"],
    supported_protocols=["uniswap_v3"],
    intent_types=["SWAP", "HOLD"],
    default_chain="arbitrum",
)
class MicroMeanRevertStrategy(IntentStrategy):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        def cfg(key: str, default: Any) -> Any:
            if isinstance(self.config, dict):
                return self.config.get(key, default)
            return getattr(self.config, key, default)

        # Token pair
        self.base_token = cfg("base_token", "WETH")
        self.quote_token = cfg("quote_token", "USDC")

        # RSI params — short period + sub-minute timeframe
        self.rsi_period = int(cfg("rsi_period", 3))
        self.rsi_timeframe = cfg("rsi_timeframe", "1m")
        self.rsi_oversold = Decimal(str(cfg("rsi_oversold", "48")))
        self.rsi_overbought = Decimal(str(cfg("rsi_overbought", "52")))

        # Position sizing: fraction of total portfolio per trade
        self.trade_pct = Decimal(str(cfg("trade_pct", "0.20")))

        # Slippage — wider for micro trades on volatile short frames
        self.max_slippage = Decimal(str(cfg("max_slippage_bps", "100"))) / Decimal("10000")

        # Circuit breaker
        self.max_consecutive_failures = int(cfg("max_consecutive_failures", 3))
        self.failure_cooldown_seconds = float(cfg("failure_cooldown_seconds", 300))
        self.consecutive_failures = 0
        self.failure_cooldown_until = 0.0

        logger.info(
            f"MicroMeanRevert initialized: {self.base_token}/{self.quote_token} "
            f"RSI({self.rsi_period}, {self.rsi_timeframe}), "
            f"trade_pct={self.trade_pct}, slippage={self.max_slippage}"
        )

    # ------------------------------------------------------------------
    # decide
    # ------------------------------------------------------------------

    def decide(self, market: MarketSnapshot) -> Optional[Intent]:
        try:
            now = time.time()

            # Circuit breaker: cooldown active
            if now < self.failure_cooldown_until:
                remaining = int(self.failure_cooldown_until - now)
                return Intent.hold(reason=f"Circuit breaker cooldown ({remaining}s left)")

            # Circuit breaker: too many consecutive failures
            if self.consecutive_failures >= self.max_consecutive_failures:
                self.failure_cooldown_until = now + self.failure_cooldown_seconds
                self.consecutive_failures = 0
                logger.warning(
                    f"Circuit breaker tripped after {self.max_consecutive_failures} failures, "
                    f"cooling down {self.failure_cooldown_seconds}s"
                )
                return Intent.hold(reason="Circuit breaker tripped")

            # Compute trade size as 20% of total portfolio
            quote_bal = market.balance(self.quote_token)
            base_bal = market.balance(self.base_token)
            total_usd = quote_bal.balance_usd + base_bal.balance_usd
            trade_size = total_usd * self.trade_pct
            logger.info(
                f"Portfolio: ${total_usd:.4f} | trade_size: ${trade_size:.4f} | "
                f"{self.quote_token}=${quote_bal.balance_usd:.4f} | "
                f"{self.base_token}=${base_bal.balance_usd:.4f}"
            )
            if trade_size <= Decimal("0"):
                return Intent.hold(reason="Portfolio value too small to trade")

            # RSI on sub-minute timeframe
            try:
                rsi = market.rsi(self.base_token, period=self.rsi_period, timeframe=self.rsi_timeframe)
            except (ValueError, Exception) as e:
                logger.warning(f"RSI unavailable: {e}")
                return Intent.hold(reason=f"RSI data unavailable: {e}")

            logger.info(f"RSI={rsi.value:.1f} | trade_size=${trade_size:.4f}")

            # BUY: oversold
            if rsi.value <= self.rsi_oversold:
                if quote_bal.balance_usd < trade_size:
                    return Intent.hold(
                        reason=f"Oversold RSI={rsi.value:.1f} but insufficient {self.quote_token}"
                    )
                logger.info(f"BUY signal: RSI={rsi.value:.1f}")
                return Intent.swap(
                    from_token=self.quote_token,
                    to_token=self.base_token,
                    amount_usd=trade_size,
                    max_slippage=self.max_slippage,
                )

            # SELL: overbought
            if rsi.value >= self.rsi_overbought:
                if base_bal.balance_usd < trade_size:
                    return Intent.hold(
                        reason=f"Overbought RSI={rsi.value:.1f} but insufficient {self.base_token}"
                    )
                logger.info(f"SELL signal: RSI={rsi.value:.1f}")
                return Intent.swap(
                    from_token=self.base_token,
                    to_token=self.quote_token,
                    amount_usd=trade_size,
                    max_slippage=self.max_slippage,
                )

            # Neutral
            return Intent.hold(
                reason=f"RSI={rsi.value:.1f} neutral [{self.rsi_oversold}-{self.rsi_overbought}]"
            )

        except Exception as e:
            logger.exception(f"Error in decide(): {e}")
            return Intent.hold(reason=f"Error: {e}")

    # ------------------------------------------------------------------
    # Execution callback + circuit breaker
    # ------------------------------------------------------------------

    def on_intent_executed(self, intent, success: bool, result):
        if success:
            self.consecutive_failures = 0
            if result and result.swap_amounts:
                logger.info(
                    f"Swap OK: {result.swap_amounts.amount_in} -> {result.swap_amounts.amount_out}"
                )
        else:
            self.consecutive_failures += 1
            logger.warning(
                f"Intent failed ({self.consecutive_failures}/{self.max_consecutive_failures})"
            )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def get_persistent_state(self) -> dict:
        return {
            "consecutive_failures": self.consecutive_failures,
            "failure_cooldown_until": self.failure_cooldown_until,
        }

    def load_persistent_state(self, state: dict) -> None:
        self.consecutive_failures = int(state.get("consecutive_failures", 0))
        self.failure_cooldown_until = float(state.get("failure_cooldown_until", 0))

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        return {
            "strategy": "micro_mean_revert",
            "chain": self.chain,
            "consecutive_failures": self.consecutive_failures,
        }

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def supports_teardown(self) -> bool:
        return True

    def generate_teardown_intents(self, mode, market=None) -> list[Intent]:
        from almanak.framework.teardown import TeardownMode

        max_slippage = Decimal("0.03") if mode == TeardownMode.HARD else Decimal("0.01")
        return [
            Intent.swap(
                from_token=self.base_token,
                to_token=self.quote_token,
                amount="all",
                max_slippage=max_slippage,
            )
        ]
