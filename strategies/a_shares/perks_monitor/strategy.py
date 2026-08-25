"""A股股东回馈羊毛监控策略。

从原 ``Python撸大A羊毛`` 项目的 ``announcement_monitor.py`` 下沉而来：
    - 公告获取：优先复用 ``core.data_feed`` 统一数据层（akshare/eastmoney），
      不再重新实现东方财富爬虫；
    - 关键词筛选：完全沿用原 ``announcement_monitor.KEYWORDS``（逐字搬运，未猜测）；
    - 推送：复用 ``core.alert.Notifier``（企业微信群机器人），不再重新实现 WeChatPusher。

命中股东回馈/羊毛公告即产出 ``Signal(direction="buy")``（利好）并推企微。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from core.alert import AlertMessage, get_notifier
from core.config import get_config
from core.data_feed import Announcement, get_data_source
from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)


# ==================== 股东回馈公告筛选关键词 ====================
# 来源：原 announcement_monitor.py 的 KEYWORDS
# （分析 2024-2026 年所有股东回馈公告标题中的高频词汇；原注释写"共25个"，
#   实际逐条清点为 27 个，此处逐字搬运，未增删、未猜测）
PERKS_KEYWORDS: list[str] = [
    # ===== 核心关键词（高命中率）=====
    "赠送",  # 赠送产品给股东 - 最核心
    "回馈",  # 回馈股东活动 - 最核心
    "股东福利",  # 股东福利活动
    "股东节",  # 上市公司股东节(如英诺特)
    # ===== 产品相关 =====
    "品鉴",  # 产品品鉴活动
    "礼品",  # 礼品发放
    "礼盒",  # 产品礼盒
    "礼包",  # 大礼包
    "体验",  # 产品体验活动
    "试用",  # 免费试用
    "样品",  # 样品发放
    # ===== 感谢/致谢类 =====
    "致谢",  # 致谢股东
    "答谢",  # 答谢活动
    "感恩",  # 感恩回馈/感恩节活动(如奥雅股份)
    "感谢",  # 感谢股东支持
    # ===== 福利/优惠类 =====
    "福利",  # 福利发放
    "优惠券",  # 优惠券领取
    "折扣券",  # 折扣券
    "专享价",  # 股东专享价格(如好想你)
    "尊享",  # 尊享权益(如五芳斋"丰年五芳")
    "免费",  # 免费领取/免票(如峨眉山A免门票)
    # ===== 自愿性披露特征词 =====
    "自愿性信息",  # 股东回馈公告通常以《关于XX活动的自愿性信息披露公告》形式发布
    "实物分红",  # 媒体对股东回馈的称呼
    "实物回馈",  # 同上
    "宠股东",  # 媒体用语
    # ===== 特定场景 =====
    "持股",  # "持股XX股以上可领取"
    "登记日",  # 股权登记日相关
]


# ==================== 默认监控股票池 ====================
# 来源：原 announcement_monitor.py 的 DEFAULT_STOCK_LIST
# （数据来源：集思录/东财/上海证券报/雪球等，2024-2026 持续更新；
#   原注释称"共52只"，实际逐条清点为 47 只，此处逐字搬运，未增删）
DEFAULT_STOCK_POOL: list[str] = [
    # ===== 原始18只 =====
    "300908",
    "002382",
    "603101",
    "600054",
    "603716",
    "002557",
    "600771",
    "836826",
    "605300",
    "300753",
    "300997",
    "605081",
    "002646",
    "002069",
    "000620",
    "000521",
    "002186",
    "002320",
    # ===== 文旅景区新增 =====
    "000888",  # 峨眉山A - 免门票+温泉滑雪
    "000978",  # 桂林旅游
    "300972",  # 祥源文旅 - 索道游船免票+酒店住一送一
    # ===== 影视娱乐新增 =====
    "001330",  # 博纳影业 - 观影券
    "001302",  # 万达电影 - 1元换观影券
    "002301",  # 横店影视 - 观影券+美食套餐
    # ===== 食品饮料新增 =====
    "603237",  # 五芳斋 - 粽子礼盒
    "603043",  # 莲花控股 - 产品礼盒
    "002702",  # 海欣食品
    "600809",  # 山西汾酒
    "600197",  # 伊力特
    "600559",  # 迎驾贡酒
    "600702",  # 舍得酒业
    "001216",  # 千味央厨 - 预制菜礼包
    "300883",  # 金龙鱼
    "600887",  # 伊利股份
    "603517",  # 绝味食品
    "002881",  # 妙可蓝多 - 奶酪五折购
    # ===== 医疗健康/科技新增 =====
    "688285",  # 英诺特 - 检测产品+iPhone抽奖
    "300122",  # 华大基因 - 基因检测产品
    "300740",  # 水羊股份 - 化妆品礼盒
    "300949",  # 奥雅股份 - 感恩回馈礼品
    "301208",  # 何氏眼科 - 医美/近视手术优惠
    "000597",  # 东北制药 - 栖芳源化妆品
    "603369",  # 苏盐井神 - 淮盐礼盒
    "002587",  # 好想你 - 年货礼盒
    # ===== 日化/消费新增 =====
    "600839",  # 四川长虹 - 电器折扣
    "603108",  # 寿仙谷 - 灵芝孢子粉折扣
    "002081",  # 圣元环保 - 牛磺酸饮料
]


# 东财公告详情页 URL 模板（沿用原 announcement_monitor 约定）
_DETAIL_URL_TPL = "https://data.eastmoney.com/notices/detail/{symbol}/{art_code}.html"


def _match_keyword(title: str) -> str | None:
    """检查标题是否命中股东回馈关键词，返回首个命中词（无则 None）。

    与原 ``announcement_monitor._check_keywords`` 行为一致：顺序遍历，首个命中即返回。
    """
    for kw in PERKS_KEYWORDS:
        if kw in title:
            return kw
    return None


def _build_detail_url(symbol: str, ann: Announcement) -> str:
    """根据 Announcement 构造东财公告详情页 URL。

    ``core.data_feed.eastmoney_source`` 把 ``art_code`` 存进 ``ann.url``；
    若 url 已是完整链接则直接用，否则按原爬虫约定拼接详情页 URL。
    """
    raw = ann.url or ""
    if raw.startswith("http"):
        return raw
    if raw:  # 视为 art_code
        return _DETAIL_URL_TPL.format(symbol=symbol, art_code=raw)
    return ""


@register_strategy(
    StrategyInfo(
        name="perks_monitor",
        market="a_shares",
        live_capable=False,
        description="上市公司股东回馈公告监控+企微推送",
    )
)
class PerksMonitorStrategy(StrategyBase):
    """股东回馈羊毛监控策略。

    - ``produce()``：拉取指定标的公告，关键词筛选命中后产出 buy 信号并推企微。
    - ``scan_announcements()``：遍历模块配置中的显式股票池（供 scheduler 调用）。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config=config)
        # 股票池必须来自调用方或模块配置。历史 DEFAULT_STOCK_POOL 仅保留为
        # 导入兼容常量，不再作为运行时回退，避免调度配置丢失时扫描示例标的。
        configured_pool = self.config.get("stock_pool")
        self._stock_pool: list[str] = (
            [str(symbol).strip() for symbol in configured_pool if str(symbol).strip()]
            if isinstance(configured_pool, (list, tuple))
            else []
        )
        # 单次拉取公告条数（原爬虫 page_size=100）
        self._limit: int = int(self.config.get("limit", 100))

    # ---------------- 公告拉取与筛选 ----------------
    def _fetch_announcements(self, symbol: str) -> list[Announcement]:
        """通过 core.data_feed 统一数据层获取个股公告。"""
        try:
            ds = get_data_source("a_shares")
            return ds.get_announcements(symbol, limit=self._limit)
        except Exception:
            logger.exception("获取公告失败: %s", symbol)
            return []

    def _filter_perks(
        self, symbol: str, anns: list[Announcement]
    ) -> list[tuple[Announcement, str]]:
        """筛选命中股东回馈关键词的公告，返回 (公告, 命中词) 列表。"""
        hits: list[tuple[Announcement, str]] = []
        for ann in anns:
            kw = _match_keyword(ann.title or "")
            if kw:
                hits.append((ann, kw))
        return hits

    # ---------------- 信号产出 ----------------
    def produce(self, symbols=None, **kwargs: Any) -> list[Signal]:
        """产出股东回馈信号。

        Args:
            symbols: 单个代码或代码列表；None 时使用模块配置股票池。
        Returns:
            命中公告对应的 Signal 列表（direction="buy"，股东回馈属利好）。
        """
        targets = self._normalize_symbols(symbols)
        if not targets:
            details = {
                "market": "a_shares",
                "reason": "未提供明确公告监控标的（调用参数 symbols 或 modules.perks_monitor.stock_pool）",
                "symbols": [],
            }
            self.last_report = {
                "kind": "perks_monitor",
                "status": "unavailable",
                "degraded": True,
                "display_only": True,
                "execution_eligible": False,
                **details,
            }
            self.last_signal_rejection = {
                "code": "symbols_required",
                "message": "公告监控未配置明确标的，未启动扫描。",
                "details": details,
            }
            logger.warning("perks_monitor 配置不完整，跳过公告扫描")
            return []
        signals: list[Signal] = []
        for sym in targets:
            anns = self._fetch_announcements(sym)
            hits = self._filter_perks(sym, anns)
            for ann, kw in hits:
                sig = self._build_signal(sym, ann, kw)
                self.publish(sig)
                signals.append(sig)
                self._push_alert(sym, ann, kw)
        if signals:
            logger.info("perks_monitor 命中 %d 条股东回馈公告", len(signals))
        return signals

    def _build_signal(self, symbol: str, ann: Announcement, kw: str) -> Signal:
        """构造单条 buy 信号。"""
        return Signal(
            symbol=symbol,
            market="a_shares",
            timeframe="daily",
            direction="buy",  # 股东回馈属利好
            score=0.8,  # 利好强度（0~1）
            confidence=0.7,  # 关键词命中置信度
            source="perks_monitor",
            tags=["perks", "a_shares", "announcement"],
            ts=datetime.now(UTC),
            meta={
                "title": ann.title,
                "ann_ts": ann.ts.isoformat() if ann.ts else None,
                "keyword": kw,
                "url": _build_detail_url(symbol, ann),
                "ann_type": ann.ann_type,
            },
        )

    def _push_alert(self, symbol: str, ann: Announcement, kw: str) -> None:
        """通过 core.alert 推送企微告警（复用 Notifier，不重新实现推送）。"""
        url = _build_detail_url(symbol, ann)
        ann_ts = ann.ts.strftime("%Y-%m-%d") if ann.ts else ""
        base = f"股票: {symbol}\n日期: {ann_ts}\n标题: {ann.title}\n命中关键词: {kw}"
        content = f"{base}\n链接: {url}" if url else base
        msg = AlertMessage(
            title=f"股东回馈公告 [{symbol}]",
            content=content,
            level="info",
            source="perks_monitor",
            tags=["perks", symbol],
        )
        try:
            get_notifier().send(msg)
        except Exception:
            logger.exception("推送告警失败: %s %s", symbol, ann.title)

    # ---------------- 工具 ----------------
    def _normalize_symbols(self, symbols) -> list[str]:
        if symbols is None:
            return list(self._stock_pool)
        if isinstance(symbols, str):
            return [symbols]
        return [str(s) for s in symbols]

    def get_stock_pool(self) -> list[str]:
        """返回当前监控股票池。"""
        return list(self._stock_pool)


def scan_announcements(symbols=None, config: dict | None = None) -> list[Signal]:
    """遍历股票池扫描股东回馈公告（供 scheduler 调用）。

    Args:
        symbols: 指定股票池；None 时使用 modules.perks_monitor.stock_pool。
        config:  策略配置 dict（与 ``a_shares.yaml: modules.perks_monitor`` 合并）。
    Returns:
        命中的 Signal 列表。
    """
    # 合并配置：a_shares.yaml 的 modules.perks_monitor + 传入 config
    merged_cfg: dict = {}
    try:
        mod_cfg = get_config("a_shares").get("modules", {}).get("perks_monitor", {})
        merged_cfg.update(mod_cfg)
    except Exception:
        logger.warning("读取 perks_monitor 模块配置失败，跳过公告扫描", exc_info=True)
    if config:
        merged_cfg.update(config)

    strategy = PerksMonitorStrategy(config=merged_cfg)
    return strategy.produce(symbols=symbols)
