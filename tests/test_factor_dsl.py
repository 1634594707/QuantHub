from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from core.factor_dsl import (
    FactorDefinition,
    FactorDslError,
    FactorDslLimits,
    FactorRegistry,
    builtin_factor_definitions,
    count_parameter_combinations,
    describe_token_formula,
    detect_series_redundancy,
    evaluate_factor_definition,
    token_formula_ast,
    validate_factor_data_coverage,
    validate_factor_definition,
)
from core.factor_research import FACTOR_META, _factor_series


def momentum_ast(periods: int = 20) -> dict:
    return {
        "op": "pct_change",
        "periods": periods,
        "value": {"op": "field", "name": "close"},
    }


class FactorDslTests(unittest.TestCase):
    def test_token_formula_ast_is_auditable_and_stack_validated(self) -> None:
        ast = token_formula_ast(
            engine="alphagpt",
            tokens=[0, 1, 2],
            feature_names=["RET", "LIQ_SCORE"],
            operators=[("ADD", 2)],
            vocab_version="v-test",
            vocab_schema="test-schema",
            input_fields=["close", "liquidity", "fdv"],
        )
        definition = FactorDefinition(
            key="alphagpt_test",
            label="AlphaGPT 测试",
            market="crypto",
            ast=ast,
        )

        details = describe_token_formula(ast)
        validation = validate_factor_definition(definition)

        self.assertEqual(details["expression"], "RET -> LIQ_SCORE -> ADD")
        self.assertEqual(validation.fields, ("close", "fdv", "liquidity"))
        with self.assertRaisesRegex(FactorDslError, "受控引擎适配器"):
            evaluate_factor_definition(definition, pd.DataFrame({"close": [1.0]}))

        with self.assertRaisesRegex(FactorDslError, "缺少操作数"):
            token_formula_ast(
                engine="alphagpt",
                tokens=[0, 2],
                feature_names=["RET", "LIQ_SCORE"],
                operators=[("ADD", 2)],
                vocab_version="v-test",
                vocab_schema="test-schema",
                input_fields=["close"],
            )

    def test_alphagpt_and_alphamaster_adapters_create_restorable_definitions(self) -> None:
        from strategies.crypto.alphagpt.formula_adapter import factor_definitions as crypto_defs
        from strategies.mt5.alphamaster.formula_adapter import factor_definitions as mt5_defs

        crypto = crypto_defs([[4, 15], [0, 14, 10]])
        mt5 = mt5_defs([[2], [9], [23]])

        self.assertEqual(len(crypto), 2)
        self.assertEqual(crypto[0].ast_payload["engine"], "alphagpt")
        self.assertIn("vocab_version", crypto[0].parameters)
        self.assertEqual(len(mt5), 3)
        self.assertEqual(mt5[0].parameters["token_names"], ["RET20"])
        self.assertEqual(mt5[1].parameters["token_names"], ["DEV"])
        self.assertEqual(mt5[2].parameters["token_names"], ["MACD_HIST"])
        self.assertTrue(mt5[0].parameters["vocab_version"].startswith("v"))

    def test_definition_hash_changes_for_parameters_and_availability(self) -> None:
        base = FactorDefinition(
            key="momentum",
            label="动量",
            market="all",
            ast=momentum_ast(20),
            parameters={"periods": 20},
        )
        parameter_changed = FactorDefinition(
            key="momentum",
            label="动量",
            market="all",
            ast=momentum_ast(60),
            parameters={"periods": 60},
        )
        delayed = FactorDefinition(
            key="momentum",
            label="动量",
            market="all",
            ast=momentum_ast(20),
            availability_lag=1,
            parameters={"periods": 20},
        )

        self.assertNotEqual(base.definition_hash, parameter_changed.definition_hash)
        self.assertNotEqual(base.definition_hash, delayed.definition_hash)

    def test_negative_lag_is_rejected_as_future_information(self) -> None:
        definition = FactorDefinition(
            key="future",
            label="未来函数",
            market="all",
            ast={
                "op": "lag",
                "periods": -1,
                "value": {"op": "field", "name": "close"},
            },
        )

        with self.assertRaisesRegex(FactorDslError, "未来数据"):
            validate_factor_definition(definition)

    def test_price_and_volume_cannot_be_added(self) -> None:
        definition = FactorDefinition(
            key="bad_units",
            label="错误单位",
            market="all",
            ast={
                "op": "add",
                "left": {"op": "field", "name": "close"},
                "right": {"op": "field", "name": "volume"},
            },
        )

        with self.assertRaisesRegex(FactorDslError, "单位不一致"):
            validate_factor_definition(definition)

    def test_complexity_budget_rejects_deep_formula(self) -> None:
        ast = {"op": "field", "name": "close"}
        for _ in range(5):
            ast = {"op": "abs", "value": ast}
        definition = FactorDefinition(key="deep", label="过深", market="all", ast=ast)

        with self.assertRaisesRegex(FactorDslError, "AST 深度"):
            validate_factor_definition(definition, FactorDslLimits(max_depth=3))

    def test_parameter_grid_budget_is_enforced(self) -> None:
        self.assertEqual(
            count_parameter_combinations({"window": [10, 20, 60], "horizon": [1, 5]}),
            6,
        )
        with self.assertRaisesRegex(FactorDslError, "参数组合数"):
            count_parameter_combinations({"window": list(range(11)), "horizon": list(range(10))})

    def test_data_coverage_excludes_warmup_but_rejects_internal_missingness(self) -> None:
        definition = FactorDefinition(
            key="momentum",
            label="动量",
            market="all",
            ast=momentum_ast(5),
        )
        frame = pd.DataFrame({"close": np.arange(1, 31, dtype=float)})
        coverage = validate_factor_data_coverage(definition, frame)
        self.assertEqual(coverage["warmup_rows"], 5)
        self.assertEqual(coverage["coverage"], 1.0)

        frame.loc[10:20, "close"] = np.nan
        with self.assertRaisesRegex(FactorDslError, "覆盖率"):
            validate_factor_data_coverage(
                definition,
                frame,
                FactorDslLimits(minimum_data_coverage=0.8),
            )

    def test_industry_neutralization_is_cross_sectional_and_unit_safe(self) -> None:
        definition = FactorDefinition(
            key="industry_neutral_momentum",
            label="行业中性动量",
            market="a_shares",
            ast={
                "op": "industry_neutralize",
                "value": {"op": "field", "name": "close"},
                "industry": {"op": "field", "name": "industry"},
                "date": {"op": "field", "name": "datetime"},
            },
        )
        frame = pd.DataFrame(
            {
                "datetime": ["2026-01-01"] * 4,
                "industry": ["科技", "科技", "金融", "金融"],
                "close": [10.0, 14.0, 20.0, 26.0],
            }
        )

        validation = validate_factor_definition(definition)
        result = evaluate_factor_definition(definition, frame)

        self.assertEqual(validation.shape, "series")
        self.assertEqual(validation.unit, "price")
        self.assertEqual(result.tolist(), [-2.0, 2.0, -3.0, 3.0])

    def test_evaluation_is_causal(self) -> None:
        definition = FactorDefinition(
            key="momentum",
            label="动量",
            market="all",
            ast=momentum_ast(5),
        )
        original = pd.DataFrame({"close": np.arange(1, 51, dtype=float)})
        changed = original.copy()
        changed.loc[40:, "close"] *= 10

        before = evaluate_factor_definition(definition, original)
        after = evaluate_factor_definition(definition, changed)

        pd.testing.assert_series_equal(before.iloc[:40], after.iloc[:40])

    def test_rank_uses_only_a_rolling_past_window(self) -> None:
        definition = FactorDefinition(
            key="rolling_rank",
            label="滚动排名",
            market="all",
            ast={
                "op": "rank",
                "window": 10,
                "value": {"op": "field", "name": "close"},
            },
        )
        original = pd.DataFrame({"close": np.arange(1, 51, dtype=float)})
        changed = original.copy()
        changed.loc[40:, "close"] *= -100

        before = evaluate_factor_definition(definition, original)
        after = evaluate_factor_definition(definition, changed)

        pd.testing.assert_series_equal(before.iloc[:40], after.iloc[:40])

    def test_builtin_factor_definitions_preserve_all_legacy_formula_outputs(self) -> None:
        close = 100 * np.exp(np.cumsum(np.linspace(-0.01, 0.012, 180)))
        frame = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": np.linspace(10_000, 50_000, len(close)),
            }
        )
        expected = _factor_series(frame)
        definitions = builtin_factor_definitions()

        self.assertEqual(len(definitions), len(FACTOR_META))
        for definition in definitions:
            actual = evaluate_factor_definition(definition, frame)
            pd.testing.assert_series_equal(
                actual,
                expected[definition.key],
                check_names=False,
            )

    def test_redundancy_detector_distinguishes_equivalence_types(self) -> None:
        base = pd.Series(np.linspace(-2, 2, 200))
        series = {
            "base": base,
            "exact": base.copy(),
            "scaled": base * 3,
            "monotonic": base.pow(3),
            "correlated": base + np.sin(np.arange(len(base))) * 0.08,
        }

        pairs = detect_series_redundancy(series)
        relation_by_pair = {
            frozenset((item["left_key"], item["right_key"])): item["relation"] for item in pairs
        }

        self.assertEqual(relation_by_pair[frozenset(("base", "exact"))], "exact_duplicate")
        self.assertEqual(relation_by_pair[frozenset(("base", "scaled"))], "constant_multiple")
        self.assertEqual(
            relation_by_pair[frozenset(("base", "monotonic"))],
            "monotonic_equivalent",
        )
        self.assertEqual(
            relation_by_pair[frozenset(("base", "correlated"))],
            "high_correlation",
        )
        base_exact = next(
            item for item in pairs if {item["left_key"], item["right_key"]} == {"base", "exact"}
        )
        self.assertAlmostEqual(base_exact["tail_pearson"], 1.0)
        self.assertGreater(base_exact["tail_observations"], 0)

    def test_registry_requires_version_change_for_definition_change(self) -> None:
        registry = FactorRegistry()
        registry.register(
            FactorDefinition(
                key="momentum",
                label="动量",
                market="all",
                ast=momentum_ast(20),
            )
        )

        with self.assertRaisesRegex(FactorDslError, "必须提升版本"):
            registry.register(
                FactorDefinition(
                    key="momentum",
                    label="动量",
                    market="all",
                    ast=momentum_ast(60),
                )
            )

        upgraded = registry.register(
            FactorDefinition(
                key="momentum",
                label="动量",
                market="all",
                ast=momentum_ast(60),
                version="2.0.0",
            )
        )
        self.assertEqual(upgraded.version, "2.0.0")

    def test_registry_detects_duplicate_formula_across_different_keys(self) -> None:
        registry = FactorRegistry()
        registry.register(
            FactorDefinition(
                key="momentum_a",
                label="动量 A",
                market="a_shares",
                ast={"op": "pct_change", "value": {"op": "field", "name": "close"}, "periods": 20},
            )
        )

        with self.assertRaisesRegex(FactorDslError, "完全重复"):
            registry.register(
                FactorDefinition(
                    key="momentum_b",
                    label="动量 B",
                    market="a_shares",
                    ast={
                        "periods": 20,
                        "value": {"name": "close", "op": "field"},
                        "op": "pct_change",
                    },
                )
            )

    def test_registry_allows_explicit_alias_in_same_factor_family(self) -> None:
        registry = FactorRegistry()
        ast = {
            "op": "rolling_zscore",
            "value": {"op": "field", "name": "close"},
            "window": 20,
        }
        canonical = registry.register(
            FactorDefinition(
                key="mean_reversion",
                label="均值回归",
                market="all",
                ast=ast,
                direction="inverse",
                family="mean_reversion",
            )
        )
        alias = registry.register(
            FactorDefinition(
                key="bollinger_reversal",
                label="布林反转",
                market="all",
                ast=ast,
                direction="inverse",
                family="mean_reversion",
            )
        )

        self.assertEqual(canonical.formula_hash, alias.formula_hash)
        self.assertNotEqual(canonical.definition_hash, alias.definition_hash)
        self.assertEqual(alias.to_dict()["input_fields"], ["close"])


if __name__ == "__main__":
    unittest.main()
