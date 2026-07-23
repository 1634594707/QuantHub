# -*- coding: utf-8 -*-
"""OKX 实盘下单适配器。

复用 ``core.data_feed.okx_source.OkxSource`` 的 ``_exchange`` 实例（ccxt.okx），
封装原 OKX Grid Master ``exchange/okx_api.py`` 的下单/查询方法。

实盘默认关闭：``live=False`` 时所有方法返回拟下单 JSON（dry-run），
不触达交易所；仅当 ``live=True`` 时才真正调用 ccxt 私有接口。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from core.data_feed.okx_source import OkxSource

logger = logging.getLogger(__name__)

# 合约网格方向常量（源自原 okx_api.CONTRACT_GRID_DIRECTION）
CONTRACT_GRID_DIRECTION = "long"


def _convert_symbol_to_instid(symbol: str) -> str:
    """将 ccxt 符号格式 (YGG/USDT:USDT) 转为 OKX 合约格式 (YGG-USDT-SWAP)。

    保持原 ``okx_api._convert_symbol_to_instid`` 实现。
    """
    return symbol.replace("/USDT:USDT", "-USDT-SWAP")


def _retry_wrapper(func, params=None, act_name="", sleep_seconds=3, retry_times=5):
    """通用重试封装器。保持原 ``okx_api.retry_wrapper`` 实现。"""
    for attempt in range(retry_times):
        try:
            if params is None:
                params = {}
            result = func(**params) if isinstance(params, dict) else func(*params)
            return result
        except Exception as e:
            logger.warning("[%s] 第%d次尝试失败: %s", act_name, attempt + 1, e)
            if attempt < retry_times - 1:
                time.sleep(sleep_seconds)
            else:
                raise ValueError(f"[{act_name}] 重试{retry_times}次均失败")


class OkxExecutor:
    """OKX 实盘下单执行器。

    - ``live=True``  : 真实下单（复用 ``OkxSource._exchange`` 的 ccxt.okx 实例）
    - ``live=False`` : 所有方法返回拟下单 JSON（dry-run），不触达交易所

    下单/查询方法对应原 ``okx_api`` 的：
        - place_grid_order  -> POST /api/v5/tradingBot/grid/order-algo
        - close_grid_order  -> POST /api/v5/tradingBot/grid/stop-order-algo
        - query_grid_orders -> GET  /api/v5/tradingBot/grid/orders-algo-pending|history
        - get_grid_profit   -> GET  /api/v5/tradingBot/grid/orders-algo-details
        - set_leverage / get_account_info / get_open_orders / cancel_order
    """

    def __init__(self, source: OkxSource, live: bool = False) -> None:
        self._source = source
        self._live = bool(live)

    # ------------------------------------------------------------------
    # 基础属性
    # ------------------------------------------------------------------

    @property
    def exchange(self):
        """底层 ccxt.okx 实例（来自 OkxSource，不重新封装 ccxt）。"""
        return self._source._exchange

    @property
    def is_live(self) -> bool:
        return self._live

    # ------------------------------------------------------------------
    # 账户与持仓
    # ------------------------------------------------------------------

    def get_account_info(self) -> dict:
        """获取账户信息和当前持仓。对应原 ``okx_api.get_account_info``。"""
        if not self._live:
            return {
                "dry_run": True,
                "action": "get_account_info",
                "totalEquity": 0.0,
                "positions": [],
            }
        account = _retry_wrapper(
            self.exchange.fetch_balance,
            params={},
            act_name="获取账户信息",
        )
        # 总权益：OKX 的 info.data[0].totalEq 为 USDT 折算总权益
        total_equity = 0.0
        info_data = account.get("info", {}).get("data", [])
        if info_data:
            total_equity = float(info_data[0].get("totalEq", 0))
        else:
            total_val = account.get("total", 0)
            if isinstance(total_val, dict):
                total_equity = float(total_val.get("USDT", 0))
            else:
                total_equity = float(total_val)

        # 持仓币种
        pos_symbols: list[str] = []
        positions = account.get("positions") or account.get("info", {}).get("data", [])
        for pos in positions:
            margin_val = pos.get("initialMargin", pos.get("mgnRatio", pos.get("margin", 0)))
            try:
                margin = float(margin_val) if margin_val not in ("", None) else 0.0
            except (ValueError, TypeError):
                margin = 0.0
            if margin <= 0:
                continue
            inst_id = pos.get("instId", pos.get("symbol", ""))
            if inst_id:
                pos_symbols.append(inst_id.replace("-USDT-SWAP", "/USDT:USDT"))

        return {
            "totalEquity": total_equity,
            "positions": pos_symbols,
            "info": account.get("info", {}),
        }

    # ------------------------------------------------------------------
    # 杠杆设置
    # ------------------------------------------------------------------

    def set_leverage(self, symbol: str, leverage: int) -> dict | None:
        """设置交易对杠杆。对应原 ``okx_api.set_leverage``。"""
        if not self._live:
            return {
                "dry_run": True,
                "action": "set_leverage",
                "symbol": symbol,
                "leverage": int(leverage),
            }
        params = {"symbol": symbol, "leverage": int(leverage), "margintype": "cross"}
        try:
            return _retry_wrapper(
                self.exchange.set_leverage,
                params=params,
                act_name=f"设置{symbol}杠杆为{leverage}x",
            )
        except Exception as e:
            logger.warning("设置%s杠杆失败(可能已存在): %s", symbol, e)
            return None

    # ------------------------------------------------------------------
    # 订单管理
    # ------------------------------------------------------------------

    def get_open_orders(self, symbol: str) -> list[dict]:
        """获取指定币种的挂单。对应原 ``okx_api.get_open_orders``。"""
        if not self._live:
            return [{"dry_run": True, "action": "get_open_orders", "symbol": symbol}]
        result = _retry_wrapper(
            self.exchange.fetch_open_orders,
            params={"symbol": symbol},
            act_name=f"查询{symbol}挂单",
        )
        return result or []

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        """撤销指定订单。对应原 ``okx_api.cancel_order``。"""
        if not self._live:
            return {
                "dry_run": True,
                "action": "cancel_order",
                "symbol": symbol,
                "order_id": order_id,
            }
        return _retry_wrapper(
            self.exchange.cancel_order,
            params={"symbol": symbol, "id": order_id},
            act_name=f"撤销{symbol}订单{order_id}",
        )

    # ------------------------------------------------------------------
    # 网格交易 API（OKX tradingBot/grid，ccxt 内置私有方法）
    # ------------------------------------------------------------------

    def place_grid_order(self, params_dict: dict) -> dict:
        """网格策略下单（OKX 合约网格 API）。

        对应原 ``okx_api.place_grid_order``，
        POST ``/api/v5/tradingBot/grid/order-algo``。

        Args:
            params_dict: 包含以下字段的字典
                - symbol      : 交易对 (如 YGG/USDT:USDT)
                - gridType    : 网格类型 (geometric=等比, arithmetic=等差)
                - upperLimit  : 网格上限价格
                - lowerLimit  : 网格下限价格
                - gridNum     : 网格数量
                - leverage    : 杠杆倍数
                - sz          : 投入金额 (USDT)
                - stopLossPx  : 网格终止最低价（可选）
                - takeProfitPx: 网格终止最高价（可选）
        Returns:
            实盘: OKX API 响应；dry-run: 拟下单 JSON
        """
        if not self._live:
            return {
                "dry_run": True,
                "action": "place_grid_order",
                "params": dict(params_dict),
                "inst_id": _convert_symbol_to_instid(params_dict.get("symbol", "")),
            }

        inst_id = _convert_symbol_to_instid(params_dict["symbol"])
        # 合约网格支持 arithmetic / geometric
        okx_grid_type = params_dict.get("gridType", "geometric")
        if okx_grid_type != "arithmetic":
            okx_grid_type = "geometric"

        algo_params = {
            "instId": inst_id,
            "algoOrdType": "contract_grid",
            "gridType": okx_grid_type,
            "gridNum": int(params_dict["gridNum"]),
            "maxPx": str(params_dict["upperLimit"]),
            "minPx": str(params_dict["lowerLimit"]),
            "lever": str(params_dict["leverage"]),
            "sz": str(params_dict["sz"]),
            "direction": CONTRACT_GRID_DIRECTION,
        }
        return _retry_wrapper(
            lambda: self.exchange.private_post_tradingbot_grid_order_algo(algo_params),
            act_name="网格下单",
        )

    def close_grid_order(self, algo_order_id: str, inst_id: str = "") -> dict:
        """关闭网格订单。对应原 ``okx_api.close_grid_order``。

        POST ``/api/v5/tradingBot/grid/stop-order-algo``。
        """
        if not self._live:
            return {
                "dry_run": True,
                "action": "close_grid_order",
                "algo_id": str(algo_order_id),
                "inst_id": inst_id,
            }
        params: dict[str, Any] = {
            "algoOrdType": "contract_grid",
            "algoId": str(algo_order_id),
        }
        if inst_id:
            params["instId"] = inst_id
        return _retry_wrapper(
            lambda: self.exchange.private_post_tradingbot_grid_stop_order_algo(params),
            act_name="关闭网格",
        )

    def query_grid_orders(self, inst_id: str = "", ord_type: str = "running") -> dict:
        """查询网格订单列表。对应原 ``okx_api.query_grid_orders``。

        Args:
            inst_id: 合约 ID（可选）
            ord_type: 'running' 或 'history'
        """
        if not self._live:
            return {
                "dry_run": True,
                "action": "query_grid_orders",
                "inst_id": inst_id,
                "ord_type": ord_type,
            }
        if ord_type == "running":
            api_method = self.exchange.private_get_tradingbot_grid_orders_algo_pending
        else:
            api_method = self.exchange.private_get_tradingbot_grid_orders_algo_history
        params: dict[str, Any] = {"algoOrdType": "contract_grid"}
        if inst_id:
            params["instId"] = inst_id
        return _retry_wrapper(lambda: api_method(params), act_name="查询网格订单")

    def get_grid_profit(self, algo_order_id: str) -> dict:
        """获取网格策略收益详情。对应原 ``okx_api.get_grid_profit``。

        GET ``/api/v5/tradingBot/grid/orders-algo-details``。
        """
        if not self._live:
            return {
                "dry_run": True,
                "action": "get_grid_profit",
                "algo_id": str(algo_order_id),
            }
        params = {"algoOrdType": "contract_grid", "algoId": str(algo_order_id)}
        return _retry_wrapper(
            lambda: self.exchange.private_get_tradingbot_grid_orders_algo_details(params),
            act_name="查询网格收益",
        )
