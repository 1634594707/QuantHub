"""Instrument 领域模型与市场推断。

设计要点：
    - ``Instrument`` 为不可变 dataclass，作为标的元数据的唯一真值源
    - ``infer_market`` 按 symbol 形态推断市场（A股6位数字 / crypto含字母 / etc.）
    - ``instrument_id`` 为 ``{market}:{code}`` 形式，跨域稳定引用
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Instrument:
    """统一标的元数据。

    Attributes:
        code:       标的代码（大写、标准化后），如 ``600519`` / ``BTC-USDT``
        market:     市场标识：``a_shares`` / ``crypto`` / ``us_stocks`` / ``mt5``
        exchange:   交易所代码（``sse`` / ``szse`` / ``okx`` / ``nasdaq``），未知为空串
        name:       中文/英文名称，如 ``贵州茅台``
        currency:   计价币种（``CNY`` / ``USD`` / ``USDT``）
        asset_class:资产类别：``stock`` / ``etf`` / ``crypto`` / ``forex`` / ``index``
    """

    code: str
    market: str
    exchange: str = ""
    name: str = ""
    currency: str = ""
    asset_class: str = "stock"

    @property
    def instrument_id(self) -> str:
        """跨域稳定引用 ID：``{market}:{code}``。"""
        return f"{self.market}:{self.code}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["instrument_id"] = self.instrument_id
        return d


# A 股代码段 → 交易所映射（用于推断 exchange）
_A_SHARE_PREFIX = {
    "60": ("sse", "sh"),  # 上海主板
    "68": ("sse", "sh"),  # 科创板
    "90": ("sse", "sh"),  # B 股
    "00": ("szse", "sz"),  # 深圳主板
    "30": ("szse", "sz"),  # 创业板
    "20": ("szse", "sz"),  # B 股
}


def infer_market(symbol: str) -> str:
    """按 symbol 形态推断市场。

    - 6 位纯数字 → a_shares
    - 含 ``-`` 或 ``/`` 且有字母 → crypto（如 BTC-USDT、ETH/USDT）
    - 1-4 位纯字母 → us_stocks / forex 兜底
    """
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return "a_shares"
    if normalized.isdigit() and len(normalized) == 6:
        return "a_shares"
    if any(c.isalpha() for c in normalized) and (
        "-" in normalized or "/" in normalized or len(normalized) >= 6
    ):
        return "crypto"
    if normalized.isalpha() and 1 <= len(normalized) <= 5:
        return "us_stocks"
    return "a_shares"


def infer_exchange(code: str, market: str) -> str:
    """按代码与市场推断交易所。"""
    if market == "a_shares" and code.isdigit() and len(code) == 6:
        prefix = code[:2]
        return _A_SHARE_PREFIX.get(prefix, ("", ""))[0]
    if market == "crypto":
        return "okx"
    if market == "us_stocks":
        return "nasdaq"
    return ""


def default_currency(market: str) -> str:
    """市场默认计价币种。"""
    if market == "a_shares":
        return "CNY"
    if market == "crypto":
        return "USDT"
    if market in ("us_stocks", "mt5"):
        return "USD"
    return ""


def build_instrument(code: str, market: str | None = None, name: str = "") -> Instrument:
    """按代码构建 Instrument，自动推断市场/交易所/币种。"""
    normalized_code = (code or "").strip().upper()
    actual_market = market or infer_market(normalized_code)
    return Instrument(
        code=normalized_code,
        market=actual_market,
        exchange=infer_exchange(normalized_code, actual_market),
        name=name.strip(),
        currency=default_currency(actual_market),
        asset_class="crypto" if actual_market == "crypto" else "stock",
    )
