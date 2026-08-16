from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from core.cost_profiles import select_reference_profile
from core.trading_costs import TradingCostProfile


class FactorFactoryGateThresholds(BaseModel):
    minimum_validation_return: float = -0.01
    minimum_confirmation_return: float = 0.0
    minimum_incremental_return: float = 0.0
    maximum_drawdown: float = Field(default=0.25, gt=0, le=1)
    minimum_validation_sharpe: float = 0.0
    minimum_confirmation_sharpe: float = 0.2
    minimum_trades: int = Field(default=1, ge=1, le=10_000)
    maximum_p_value: float = Field(default=0.2, gt=0, le=1)
    minimum_paper_return: float = 0.0
    maximum_paper_drawdown: float = Field(default=0.15, gt=0, le=1)
    minimum_fill_rate: float = Field(default=0.95, ge=0, le=1)
    minimum_capacity_ratio: float = Field(default=0.0, ge=0)
    minimum_observations: int = Field(default=3, ge=2, le=10_000)


class ManualAlphaCandidate(BaseModel):
    candidate_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=72,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$",
    )
    label: str | None = Field(default=None, min_length=1, max_length=120)
    family: str = Field(default="manual_alpha", min_length=1, max_length=80)
    expression: str | None = Field(default=None, min_length=1, max_length=5_000)
    formula_ast: dict[str, Any] | None = None
    hypothesis: str = Field(
        default="The manually supplied alpha may retain after-cost predictive value.",
        min_length=1,
        max_length=2_000,
    )
    invalidation: str = Field(
        default="The alpha fails rolling validation, drawdown, or doubled-cost stress.",
        min_length=1,
        max_length=2_000,
    )
    falsification_tests: list[str] = Field(
        default_factory=lambda: [
            "rolling_validation_stability",
            "double_cost_stress",
        ],
        min_length=1,
        max_length=10,
    )

    @model_validator(mode="after")
    def validate_formula_source(self):
        if (self.expression is None) == (self.formula_ast is None):
            raise ValueError("手工 Alpha 必须且只能提供 expression 或 formula_ast 之一")
        return self


class FactorFactoryStartRequest(BaseModel):
    experiment_nonce: str | None = Field(
        default=None,
        min_length=8,
        max_length=80,
        pattern=r"^[a-zA-Z0-9._:-]+$",
    )
    market: Literal["crypto", "a_shares"] = "crypto"
    source: Literal["okx_local", "okx_live", "akshare_live", "synthetic"] = "okx_local"
    symbol: str = Field(default="BTCUSDT", min_length=1, max_length=40)
    dataset: str = Field(default="uptrend", min_length=1, max_length=40)
    seed: int = Field(default=12, ge=0, le=2**32 - 1)
    interval: Literal["1h", "4h", "1d"] = "1d"
    n_bars: int = Field(default=720, ge=240, le=5_000)
    candidate_budget: int = Field(default=30, ge=1, le=30)
    candidate_mode: Literal["brain", "library", "manual"] = "brain"
    alpha_brief: str = Field(
        default=(
            "Find causal price-volume alpha expressions with stable after-cost returns, "
            "controlled drawdown, and nearby-parameter robustness."
        ),
        min_length=10,
        max_length=2_000,
    )
    use_ai: bool = True
    ai_provider: Literal["deepseek", "openai", "custom"] | None = None
    ai_candidate_count: int = Field(default=6, ge=0, le=30)
    maximum_ai_tokens: int = Field(default=12_000, ge=0, le=100_000)
    manual_candidates: list[ManualAlphaCandidate] = Field(default_factory=list, max_length=30)
    horizon: int = Field(default=5, ge=1, le=60)
    commission_bps: float | None = Field(default=None, ge=0, le=200)
    cost_profile_id: str | None = Field(default=None, max_length=120)
    cost_profile_version: str | None = Field(default=None, max_length=40)
    transaction_cost_profile: TradingCostProfile | None = None
    initial_capital: float = Field(default=1_000_000, gt=0, le=1e12)
    observation_days: int = Field(default=7, ge=7, le=365)
    paper_target: Literal["simulation_orders", "okx_demo"] = "simulation_orders"
    maximum_demo_exposure: float = Field(default=0.1, gt=0, le=0.25)
    maximum_demo_loss: float = Field(default=25.0, gt=0, le=10_000)
    thresholds: FactorFactoryGateThresholds = Field(default_factory=FactorFactoryGateThresholds)

    @model_validator(mode="after")
    def normalize_market_context(self):
        self.symbol = self.symbol.strip().upper()
        if self.market == "crypto" and self.source == "okx_live" and "-" not in self.symbol:
            if self.symbol.endswith("USDT"):
                self.symbol = f"{self.symbol[:-4]}-USDT-SWAP"
        if self.market == "crypto" and self.source == "akshare_live":
            raise ValueError("加密资产研究不能使用 akshare_live")
        if self.market == "a_shares":
            if self.source != "akshare_live":
                raise ValueError("A 股研究必须使用 akshare_live")
            if self.interval not in {"1h", "1d"}:
                raise ValueError("A 股因子工厂当前支持 1h 或 1d")
            if self.paper_target == "okx_demo":
                raise ValueError("A 股研究只能进入本地独立模拟账户")
        if self.paper_target == "okx_demo":
            if self.source != "okx_live":
                raise ValueError("OKX Demo 自动观察必须使用 okx_live 公共行情")
            if not self.symbol.endswith("-USDT-SWAP"):
                raise ValueError("OKX Demo 自动观察只支持 USDT 永续合约")
            if self.interval not in {"1h", "4h"}:
                raise ValueError("OKX Demo 策略包只支持 1h 或 4h 信号频率")
        if self.transaction_cost_profile is not None:
            profile = self.transaction_cost_profile
            if profile.market != self.market:
                raise ValueError("transaction_cost_profile.market 与因子工厂市场不一致")
        else:
            profile = select_reference_profile(
                self.market,
                profile_id=self.cost_profile_id,
                version=self.cost_profile_version,
            )
            self.transaction_cost_profile = profile
        self.cost_profile_id = profile.profile_id
        self.cost_profile_version = profile.version
        self.commission_bps = profile.total_transaction_cost_bps
        if self.candidate_mode == "manual":
            if not self.manual_candidates:
                raise ValueError("manual 模式至少需要一个手工 Alpha")
            if len(self.manual_candidates) > self.candidate_budget:
                raise ValueError("手工 Alpha 数量不能超过 candidate_budget")
            candidate_ids = [
                (candidate.candidate_id or f"manual_alpha_{index}").lower().replace("-", "_")
                for index, candidate in enumerate(self.manual_candidates, start=1)
            ]
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("手工 Alpha 的 candidate_id 不能重复")
            self.use_ai = False
            self.ai_candidate_count = 0
        elif self.manual_candidates:
            raise ValueError("manual_candidates 只能用于 manual 候选模式")
        if self.ai_candidate_count > self.candidate_budget:
            raise ValueError("ai_candidate_count 不能超过 candidate_budget")
        if self.candidate_mode != "brain" or not self.use_ai:
            self.use_ai = False
            self.ai_provider = None
            self.ai_candidate_count = 0
        elif self.ai_candidate_count > 0 and self.maximum_ai_tokens <= 0:
            raise ValueError("启用 AI 候选时 maximum_ai_tokens 必须大于 0")
        return self


class FactorFactoryObserveRequest(BaseModel):
    force_refresh: bool = False


class FactorFactoryValuationRequest(BaseModel):
    stream_id: str | None = Field(default=None, min_length=1, max_length=120)


class FactorFactoryCohortReviewRequest(BaseModel):
    provider: Literal["deepseek", "openai", "custom"] | None = None


class FactorFactoryLiveRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=1_000)


class FactorFactoryManualApproval(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    symbol: str = Field(min_length=1, max_length=40)
    interval: Literal["1h", "4h", "1d"]
    factor_version: str = Field(min_length=1, max_length=80)
    strategy_version: str = Field(default="cohort-execution-v1", min_length=1, max_length=80)
    maximum_capital: float = Field(gt=0)
    maximum_exposure: float = Field(gt=0, le=1)
    maximum_loss: float = Field(gt=0)
    valid_until: str = Field(min_length=1, max_length=64)
    risks_acknowledged: bool
