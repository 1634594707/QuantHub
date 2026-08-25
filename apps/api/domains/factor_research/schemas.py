from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from core.cost_profiles import select_reference_profile
from core.trading_costs import TradingCostProfile


class FactorDefinitionCreate(BaseModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=120)
    market: Literal["a_shares", "us_stocks", "crypto", "mt5", "all"]
    ast: dict[str, Any]
    direction: Literal["positive", "inverse"] = "positive"
    horizon: int = Field(default=5, ge=1, le=60)
    availability_lag: int = Field(default=0, ge=0, le=500)
    rationale: str = Field(default="", max_length=2_000)
    family: str | None = Field(default=None, min_length=1, max_length=80)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    parameters: dict[str, Any] = Field(default_factory=dict)


class FactorCandidateValidationRequest(BaseModel):
    factor_key: str = Field(min_length=1, max_length=80)
    factor_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=20_000)
    minimum_data_coverage: float = Field(default=0.8, gt=0, le=1)


class FactorDefinitionRef(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")


class TokenFormulaImportRequest(BaseModel):
    engine: Literal["alphagpt", "alphamaster"]
    formulas: list[list[int]] = Field(min_length=1, max_length=100)
    key_prefix: str = Field(
        default="token_factor", min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$"
    )
    label_prefix: str = Field(default="Token 因子", min_length=1, max_length=100)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    horizon: int = Field(default=5, ge=1, le=60)
    availability_lag: int = Field(default=0, ge=0, le=500)
    rationale: str = Field(default="", max_length=2_000)

    @field_validator("formulas")
    @classmethod
    def validate_formula_budget(cls, formulas: list[list[int]]) -> list[list[int]]:
        for index, formula in enumerate(formulas):
            if not formula:
                raise ValueError(f"第 {index + 1} 条公式不能为空")
            if len(formula) > 200:
                raise ValueError(f"第 {index + 1} 条公式超过 200 个 token")
        return formulas


class FactorLifecycleTransitionRequest(BaseModel):
    state: Literal[
        "exploratory",
        "research_passed",
        "trading_validated",
        "degraded",
        "retired",
    ]
    target_market: Literal["a_shares", "us_stocks", "crypto", "mt5"]
    actor_type: Literal["system", "researcher", "ai"] = "researcher"
    actor: str = Field(min_length=1, max_length=120)
    rule: str = Field(min_length=1, max_length=120)
    evidence: dict[str, Any] = Field(min_length=1)


class FactorRedundancyRequest(BaseModel):
    definitions: list[FactorDefinitionRef] = Field(min_length=2, max_length=100)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=20_000)
    minimum_observations: int = Field(default=30, ge=5, le=20_000)
    high_correlation_threshold: float = Field(default=0.95, ge=0.5, le=1)
    monotonic_threshold: float = Field(default=0.999, ge=0.9, le=1)
    tail_quantile: float = Field(default=0.1, gt=0, le=0.5)
    regime_field: str | None = Field(default="market_regime", min_length=1, max_length=80)


class FactorRobustnessRequest(BaseModel):
    factor: list[float | None] = Field(min_length=30, max_length=20_000)
    label: list[float | None] = Field(min_length=30, max_length=20_000)
    liquidity: list[float | None] | None = Field(default=None, min_length=30, max_length=20_000)
    deployed_factors: dict[str, list[float | None]] = Field(default_factory=dict)
    parameter_results: list[dict[str, Any]] = Field(default_factory=list, max_length=1_000)
    parameter_name: str | None = Field(default=None, min_length=1, max_length=80)
    parameter_metric: str | None = Field(default=None, min_length=1, max_length=80)
    parameter_threshold: float | None = None
    pareto_candidates: list[dict[str, Any]] = Field(default_factory=list, max_length=1_000)
    pareto_objectives: dict[str, Literal["maximize", "minimize"]] = Field(default_factory=dict)
    factor_returns: dict[str, list[float | None]] = Field(default_factory=dict)
    expected_ics: dict[str, float] = Field(default_factory=dict)
    candidate_portfolio_returns: list[float | None] | None = Field(
        default=None, min_length=3, max_length=20_000
    )
    benchmark_portfolio_returns: list[float | None] | None = Field(
        default=None, min_length=3, max_length=20_000
    )
    candidate_turnover: list[float | None] | None = Field(
        default=None, min_length=3, max_length=20_000
    )
    benchmark_turnover: list[float | None] | None = Field(
        default=None, min_length=3, max_length=20_000
    )
    candidate_capacity: list[float | None] | None = Field(
        default=None, min_length=3, max_length=20_000
    )
    benchmark_capacity: list[float | None] | None = Field(
        default=None, min_length=3, max_length=20_000
    )
    transaction_cost_bps: float = Field(default=10.0, ge=0, le=200)
    risk_constraints: dict[str, float] = Field(default_factory=dict)
    nonlinear_features: dict[str, list[float | None]] = Field(default_factory=dict)
    nonlinear_label: list[float | None] | None = Field(
        default=None, min_length=30, max_length=20_000
    )
    nonlinear_minimum_improvement: float = Field(default=0.02, ge=0, le=1)
    seed: int = Field(default=0, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def validate_robustness_lengths(self) -> FactorRobustnessRequest:
        expected = len(self.factor)
        if len(self.label) != expected:
            raise ValueError("factor 与 label 长度必须一致")
        if self.liquidity is not None and len(self.liquidity) != expected:
            raise ValueError("liquidity 与 factor 长度必须一致")
        for key, values in self.deployed_factors.items():
            if len(values) != expected:
                raise ValueError(f"deployed_factors.{key} 与 factor 长度必须一致")
        parameter_fields = (
            self.parameter_name,
            self.parameter_metric,
            self.parameter_threshold,
        )
        if self.parameter_results and any(value is None for value in parameter_fields):
            raise ValueError("参数平台测试必须提供 parameter_name、parameter_metric 和阈值")
        if self.pareto_candidates and not self.pareto_objectives:
            raise ValueError("Pareto 候选必须提供 pareto_objectives")
        portfolio_lengths = {
            len(values)
            for values in (
                self.candidate_portfolio_returns,
                self.benchmark_portfolio_returns,
                self.candidate_turnover,
                self.benchmark_turnover,
                self.candidate_capacity,
                self.benchmark_capacity,
            )
            if values is not None
        }
        if len(portfolio_lengths) > 1:
            raise ValueError("组合增量价值序列长度必须一致")
        if (self.candidate_portfolio_returns is None) != (self.benchmark_portfolio_returns is None):
            raise ValueError("组合增量价值必须同时提供候选和基准收益")
        if bool(self.nonlinear_features) != (self.nonlinear_label is not None):
            raise ValueError("非线性对照必须同时提供 nonlinear_features 和 nonlinear_label")
        if self.nonlinear_features:
            if len(self.nonlinear_features) < 2:
                raise ValueError("非线性对照至少需要两个特征")
            nonlinear_expected = len(self.nonlinear_label or [])
            for key, values in self.nonlinear_features.items():
                if len(values) != nonlinear_expected:
                    raise ValueError(f"nonlinear_features.{key} 与 nonlinear_label 长度必须一致")
        return self


class FactorPortfolioConstraintRequest(BaseModel):
    market: Literal["a_shares", "us_stocks", "crypto", "mt5"]
    weights: dict[str, float] = Field(min_length=1, max_length=10_000)
    industries: dict[str, str] = Field(default_factory=dict, max_length=10_000)
    benchmark_industry_weights: dict[str, float] = Field(default_factory=dict, max_length=1_000)
    average_daily_values: dict[str, float] = Field(default_factory=dict, max_length=10_000)
    proposed_trade_values: dict[str, float] = Field(default_factory=dict, max_length=10_000)
    turnover: float = Field(ge=0)
    overrides: dict[str, float | bool] = Field(default_factory=dict, max_length=10)


class FactorCandidateInboxItem(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=120)
    source: Literal["human", "ai", "template", "random_dsl", "symbolic_regression"]
    economic_hypothesis: str = Field(min_length=1, max_length=2_000)
    formula_ast: dict[str, Any] = Field(min_length=1)
    data_requirements: list[str] = Field(min_length=1, max_length=100)
    duplicate_risk: Literal["low", "medium", "high", "confirmed_duplicate"]
    future_information_check_passed: bool
    causal_check_passed: bool
    data_check_passed: bool
    estimated_compute_units: int = Field(ge=1, le=100_000_000)
    exploration_score: float | None = None
    research_status: str = Field(default="not_started", max_length=80)
    trading_status: str = Field(default="not_validated", max_length=80)
    ai_review: dict[str, Any] | None = None
    approved_by: str | None = Field(default=None, min_length=1, max_length=120)
    budget_approved: bool = False


class FactorCandidateInboxRequest(BaseModel):
    candidates: list[FactorCandidateInboxItem] = Field(min_length=1, max_length=10_000)

    @field_validator("candidates")
    @classmethod
    def validate_unique_candidate_ids(
        cls, candidates: list[FactorCandidateInboxItem]
    ) -> list[FactorCandidateInboxItem]:
        identifiers = [item.candidate_id for item in candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate_id 必须全局唯一")
        return candidates


class FactorRetirementImpactRequest(BaseModel):
    factor_key: str = Field(min_length=1, max_length=80)
    replacement_factor_key: str | None = Field(default=None, min_length=1, max_length=80)
    strategies: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)
    portfolio_allocations: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)


class FactorLineageRequest(BaseModel):
    target_market: Literal["a_shares", "us_stocks", "crypto", "mt5"] | None = None


class FactorDriftMonitoringRequest(BaseModel):
    factor_key: str = Field(min_length=1, max_length=80)
    factor_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    target_market: Literal["a_shares", "us_stocks", "crypto", "mt5"] = "a_shares"
    auto_degrade: bool = True
    reference_values: list[float] = Field(min_length=20, max_length=20_000)
    current_values: list[float] = Field(min_length=20, max_length=20_000)
    reference_ic: float
    current_ic: float
    reference_coverage: float = Field(ge=0, le=1)
    current_coverage: float = Field(ge=0, le=1)
    current_cost_bps: float = Field(ge=0)
    current_capacity_ratio: float = Field(ge=0)
    reference_correlated_factors: dict[str, list[float]] = Field(default_factory=dict)
    current_correlated_factors: dict[str, list[float]] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(min_length=7)
    affected_strategies: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)


class FactorSimulationValidationRequest(BaseModel):
    completed_rebalance_cycles: int = Field(ge=0, le=100_000)
    after_cost_return: float
    fill_rate: float = Field(ge=0, le=1)
    capacity_ratio: float = Field(ge=0)
    thresholds: dict[str, float] = Field(min_length=3)
    execution_records: list[dict[str, Any]] = Field(default_factory=list, max_length=100_000)


class FactorSimulationAttributionRequest(BaseModel):
    research_returns: list[float] = Field(min_length=1, max_length=100_000)
    simulation_returns: list[float] = Field(min_length=1, max_length=100_000)
    signal_decay: list[float] = Field(min_length=1, max_length=100_000)
    data_delay: list[float] = Field(min_length=1, max_length=100_000)
    execution: list[float] = Field(min_length=1, max_length=100_000)
    costs: list[float] = Field(min_length=1, max_length=100_000)
    portfolio_constraints: list[float] = Field(min_length=1, max_length=100_000)
    research_metrics: dict[str, float] = Field(min_length=5)
    simulation_metrics: dict[str, float] = Field(min_length=5)

    @model_validator(mode="after")
    def validate_attribution_lengths(self) -> FactorSimulationAttributionRequest:
        lengths = {
            len(self.research_returns),
            len(self.simulation_returns),
            len(self.signal_decay),
            len(self.data_delay),
            len(self.execution),
            len(self.costs),
            len(self.portfolio_constraints),
        }
        if len(lengths) != 1:
            raise ValueError("研究与模拟收益归因序列长度必须一致")
        return self


class FactorDiscoveryCandidate(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=120)
    source: Literal["ai", "template", "random_dsl", "symbolic_regression"]
    validation_passed: bool
    duplicate: bool
    research_passed: bool = False
    compute_units: int = Field(default=0, ge=0, le=100_000_000)
    llm_tokens: int = Field(default=0, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def validate_passed_candidate(self) -> FactorDiscoveryCandidate:
        if self.research_passed and (not self.validation_passed or self.duplicate):
            raise ValueError("research_passed 候选必须先通过校验且不是重复公式")
        return self


class FactorDiscoveryEfficiencyRequest(BaseModel):
    candidates: list[FactorDiscoveryCandidate] = Field(min_length=4, max_length=40_000)
    per_source_budget: int = Field(ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_source_coverage(self) -> FactorDiscoveryEfficiencyRequest:
        identifiers = [item.candidate_id for item in self.candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate_id 必须全局唯一")
        required = {"ai", "template", "random_dsl", "symbolic_regression"}
        missing = sorted(required - {item.source for item in self.candidates})
        if missing:
            raise ValueError(f"发现效率对照缺少来源: {', '.join(missing)}")
        return self


class FactorPreRegistration(BaseModel):
    primary_metric: str = Field(min_length=1, max_length=120)
    secondary_metrics: list[str] = Field(default_factory=list, max_length=20)
    pass_criteria: dict[str, Any] = Field(min_length=1)
    maximum_candidates: int = Field(default=1, ge=1, le=1_000)
    maximum_llm_tokens: int = Field(default=0, ge=0, le=10_000_000)
    confirmation_set_openings: int = Field(default=0, ge=0, le=1)


class FactorResearchDataPartition(BaseModel):
    start: date
    end: date
    data_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")

    @model_validator(mode="after")
    def validate_partition_dates(self) -> FactorResearchDataPartition:
        if self.start > self.end:
            raise ValueError("数据分区 start 不能晚于 end")
        return self


class FactorResearchDataSplit(BaseModel):
    discovery: FactorResearchDataPartition
    rolling_validation: FactorResearchDataPartition
    locked_confirmation: FactorResearchDataPartition
    purge_periods: int = Field(ge=1, le=500)
    embargo_periods: int = Field(ge=0, le=500)

    @model_validator(mode="after")
    def validate_partition_order(self) -> FactorResearchDataSplit:
        if self.discovery.end >= self.rolling_validation.start:
            raise ValueError("发现集必须早于滚动验证集")
        if self.rolling_validation.end >= self.locked_confirmation.start:
            raise ValueError("滚动验证集必须早于锁定确认集")
        return self


class FactorResearchPlanCreate(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    target_market: Literal["a_shares", "us_stocks", "crypto", "mt5"]
    maximum_candidates: int = Field(ge=1, le=100_000)
    maximum_compute_units: int = Field(ge=1, le=100_000_000)
    maximum_llm_tokens: int = Field(default=0, ge=0, le=100_000_000)
    maximum_confirmation_set_openings: int = Field(default=0, ge=0, le=1)
    maximum_round_candidates: int = Field(default=100, ge=1, le=10_000)
    maximum_formula_complexity: int = Field(default=30, ge=1, le=200)
    maximum_duplicate_rate: float = Field(default=0.25, ge=0, le=1)
    stop_conditions: dict[str, Any] = Field(default_factory=dict)
    data_split: FactorResearchDataSplit | None = None


class FactorConfirmationSetOpenRequest(BaseModel):
    experiment_id: str = Field(min_length=1, max_length=64)
    confirmation_data_fingerprint: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$"
    )
    opened_by: str = Field(min_length=1, max_length=120)
    irreversible_ack: bool

    @field_validator("irreversible_ack")
    @classmethod
    def require_irreversible_ack(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("开启锁定确认集必须明确确认不可逆")
        return value


class FactorExperimentCreate(BaseModel):
    research_plan_id: str = Field(min_length=1, max_length=80)
    hypothesis: str = Field(min_length=1, max_length=2_000)
    source: Literal[
        "human", "ai", "template", "random_dsl", "symbolic_regression", "parameter_search"
    ]
    parent_experiment_id: str | None = Field(default=None, min_length=1, max_length=64)
    factor_key: str = Field(min_length=1, max_length=80)
    factor_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    candidate_validation_id: str = Field(min_length=1, max_length=64)
    target_market: Literal["a_shares", "us_stocks", "crypto", "mt5"]
    data_start: date | None = None
    data_end: date | None = None
    parameter_grid: dict[str, Any] = Field(default_factory=dict)
    estimated_compute_units: int = Field(default=1, ge=1, le=10_000_000)
    model: dict[str, Any] = Field(default_factory=dict)
    prompt: dict[str, Any] = Field(default_factory=dict)
    applicable_regimes: list[str] = Field(default_factory=list, max_length=20)
    invalidation_conditions: list[str] = Field(default_factory=list, max_length=20)
    falsification_tests: list[str] = Field(default_factory=list, max_length=20)
    ai_trace: dict[str, Any] = Field(default_factory=dict)
    pre_registration: FactorPreRegistration

    @model_validator(mode="after")
    def validate_experiment_contract(self) -> FactorExperimentCreate:
        if self.data_start and self.data_end and self.data_start > self.data_end:
            raise ValueError("data_start 不能晚于 data_end")
        if self.source == "ai":
            if (
                not self.model.get("provider")
                or not self.model.get("model")
                or "temperature" not in self.model
            ):
                raise ValueError("AI 实验必须记录 provider、model 与 temperature")
            if not self.prompt.get("version") or not self.prompt.get("input_fingerprint"):
                raise ValueError("AI 实验必须记录提示词版本与输入指纹")
            if "token_usage" not in self.ai_trace or not self.ai_trace.get("output_raw"):
                raise ValueError("AI 实验必须记录 token 用量与输出原文")
            if not self.invalidation_conditions or not self.falsification_tests:
                raise ValueError("AI 实验必须声明失效条件与建议证伪实验")
        return self


class FactorExperimentEventCreate(BaseModel):
    status: Literal["queued", "running", "succeeded", "failed", "rejected", "cancelled"]
    result: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = Field(default=None, max_length=2_000)
    failure_code: (
        Literal[
            "duplicate_formula",
            "future_information",
            "insufficient_coverage",
            "cost_too_high",
            "unstable_regime",
            "target_market_mismatch",
            "invalid_syntax",
            "complexity_budget",
            "execution_constraint",
            "other",
        ]
        | None
    ) = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event_payload(self) -> FactorExperimentEventCreate:
        if self.status == "succeeded" and not self.result:
            raise ValueError("成功事件必须保存结果")
        if self.status in {"failed", "rejected"} and not self.failure_reason:
            raise ValueError("失败或拒绝事件必须保存原因")
        if self.status in {"failed", "rejected"} and not self.failure_code:
            raise ValueError("失败或拒绝事件必须保存结构化 failure_code")
        return self


class FactorAiSearchRoundRequest(BaseModel):
    round_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    candidate_count: int = Field(ge=1, le=10_000)
    duplicate_count: int = Field(default=0, ge=0, le=10_000)
    formula_complexities: list[int] = Field(min_length=1, max_length=10_000)
    llm_tokens: int = Field(default=0, ge=0, le=10_000_000)
    input_fingerprint: str = Field(min_length=64, max_length=128, pattern=r"^[0-9a-fA-F]+$")
    approved_by: str = Field(min_length=1, max_length=120)
    approved_candidate_ids: list[str] = Field(min_length=1, max_length=10_000)
    budget_approved_ack: bool

    @model_validator(mode="after")
    def validate_round_counts(self) -> FactorAiSearchRoundRequest:
        if self.duplicate_count > self.candidate_count:
            raise ValueError("duplicate_count 不能超过 candidate_count")
        if len(self.formula_complexities) != self.candidate_count:
            raise ValueError("formula_complexities 必须逐一对应本轮候选")
        if any(complexity < 1 or complexity > 200 for complexity in self.formula_complexities):
            raise ValueError("公式复杂度必须在 1 到 200 之间")
        if self.budget_approved_ack is not True:
            raise ValueError("启动大规模搜索前必须由研究人员批准候选和预算")
        return self


class FactorResearchRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    market: str = Field(default="a_shares")
    interval: str = Field(default="1d")
    limit: int = Field(default=500, ge=120, le=5_000)
    horizon: int = Field(default=5, ge=1, le=60)
    transaction_cost_bps: float = Field(default=10.0, ge=0, le=200)
    transaction_cost_profile: TradingCostProfile | None = None
    cost_profile_id: str | None = None
    cost_profile_version: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    walk_forward_mode: Literal["expanding", "rolling"] = "expanding"
    walk_forward_folds: int = Field(default=3, ge=1, le=10)
    availability_lag: int = Field(default=0, ge=0, le=500)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("标的代码不能为空")
        return normalized

    @field_validator("market")
    @classmethod
    def validate_market(cls, value: str) -> str:
        if value not in {"a_shares", "us_stocks", "crypto", "mt5"}:
            raise ValueError("不支持的市场")
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> FactorResearchRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        if self.transaction_cost_profile is None and self.cost_profile_id:
            self.transaction_cost_profile = select_reference_profile(
                self.market,
                profile_id=self.cost_profile_id,
                version=self.cost_profile_version,
            )
        if self.transaction_cost_profile is not None:
            if self.transaction_cost_profile.market != self.market:
                raise ValueError("transaction_cost_profile.market 与研究市场不一致")
            total_bps = self.transaction_cost_profile.total_transaction_cost_bps
            if total_bps > 200:
                raise ValueError("transaction_cost_profile 总成本不能超过 200 bp")
            self.transaction_cost_bps = total_bps
            self.cost_profile_id = self.transaction_cost_profile.profile_id
            self.cost_profile_version = self.transaction_cost_profile.version
        return self


class FactorAiReviewRequest(FactorResearchRequest):
    """AI review is bound to one saved server-side research snapshot."""

    review_focus: str = Field(default="稳健性与失效风险", max_length=120)
    run_id: str = Field(..., min_length=1, max_length=64)


class FactorUniverseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    market: Literal["a_shares", "us_stocks", "crypto", "mt5"]
    description: str = Field(default="", max_length=300)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class FactorUniverseMemberUpsert(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    effective_from: date
    effective_to: date | None = None
    status: Literal["active", "suspended", "delisted"] = "active"
    industry: str = Field(default="", max_length=80)
    market_cap: float | None = Field(default=None, gt=0)
    beta: float | None = Field(default=None, ge=-10, le=10)
    is_st: bool = False
    listed_at: date | None = None
    delisted_at: date | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_member_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("industry")
    @classmethod
    def normalize_industry(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_member_dates(self) -> FactorUniverseMemberUpsert:
        if self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from 不能晚于 effective_to")
        if self.listed_at and self.delisted_at and self.listed_at > self.delisted_at:
            raise ValueError("listed_at 不能晚于 delisted_at")
        return self


class FactorUniverseBatchRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=128)
    source: str = Field(default="manual_import", min_length=1, max_length=120)
    filename: str | None = Field(default=None, max_length=240)
    content_base64: str | None = None
    rows: list[FactorUniverseMemberUpsert] = Field(default_factory=list, max_length=20_000)

    @model_validator(mode="after")
    def validate_batch_source(self):
        if bool(self.filename and self.content_base64) == bool(self.rows):
            raise ValueError("必须且只能提供文件内容或结构化 rows")
        return self


class FactorUniverseRollbackRequest(BaseModel):
    version_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class CrossSectionResearchRequest(BaseModel):
    run_id: str | None = Field(default=None, min_length=1, max_length=64)
    universe_id: str = Field(min_length=1, max_length=64)
    factor_key: str = Field(default="trend_strength", min_length=1, max_length=60)
    interval: Literal["1d"] = "1d"
    limit: int = Field(default=500, ge=120, le=5_000)
    horizon: int = Field(default=5, ge=1, le=60)
    start_date: date | None = None
    end_date: date | None = None
    quantiles: int = Field(default=5, ge=2, le=10)
    min_assets: int = Field(default=5, ge=3, le=500)
    transaction_cost_bps: float = Field(default=10.0, ge=0, le=200)
    transaction_cost_profile: TradingCostProfile | None = None
    cost_profile_id: str | None = None
    cost_profile_version: str | None = None
    participation_rate: float = Field(default=0.1, gt=0, le=0.5)
    portfolio_mode: Literal["cohort", "non_overlapping"] = "cohort"
    neutralize_industry: bool = True
    neutralize_market_cap: bool = True
    neutralize_beta: bool = True
    retry_attempts: int = Field(default=2, ge=1, le=5)

    @model_validator(mode="after")
    def validate_cross_section_dates(self) -> CrossSectionResearchRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        if self.transaction_cost_profile is not None:
            if self.transaction_cost_profile.market not in {
                "a_shares",
                "us_stocks",
                "crypto",
                "mt5",
            }:
                raise ValueError("transaction_cost_profile.market 不受支持")
            total_bps = self.transaction_cost_profile.total_transaction_cost_bps
            if total_bps > 200:
                raise ValueError("transaction_cost_profile 总成本不能超过 200 bp")
            self.transaction_cost_bps = total_bps
            if self.transaction_cost_profile.participation_rate is not None:
                self.participation_rate = self.transaction_cost_profile.participation_rate
        return self
