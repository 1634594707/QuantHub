"""FinBERT2 中文新闻情绪分析器。

从原 ``市场情绪系统`` 的 ``core/sentiment.py`` 提取核心推理逻辑，改造为
QuantHub 风格的懒加载封装：

    - 模型路径取自 core.config（``models_dir`` / ``modules.sentiment.model_dir``）
    - transformers / torch 仅在首次推理时导入，避免 import 即加载重型依赖
    - 降级链：transformers(FinBERT2 本地权重) → snownlp → 关键词规则

模型权重文件 (.safetensors) 不随模块移动，运行时按上述配置路径引用；
若路径不存在或依赖缺失，自动降级，不抛异常。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


# 否定词表（关键词降级时反转情感），源自原 core/sentiment.py
_NEGATION_WORDS = [
    "不",
    "没有",
    "无",
    "未",
    "并非",
    "绝非",
    "不是",
    "不会",
    "不可能",
    "难以",
    "不足",
    "不佳",
    "不利",
    "不愿",
    "未能",
    "不要",
    "别",
    "莫",
    "毋",
    "勿",
    "不必",
    "尚未",
]

# 程度副词（增强/减弱情感强度），源自原 core/sentiment.py
_INTENSIFIERS = {
    "非常": 1.5,
    "极其": 2.0,
    "十分": 1.5,
    "极度": 2.0,
    "较为": 0.7,
    "略微": 0.5,
    "稍微": 0.5,
    "有点": 0.6,
    "明显": 1.3,
    "显著": 1.3,
    "大幅": 1.5,
    "持续": 1.2,
    "强烈": 1.8,
    "高度": 1.5,
    "特别": 1.4,
}

# 正面关键词（降级用），源自原 config.POSITIVE_KEYWORDS
_POSITIVE_KEYWORDS = [
    "利好",
    "增长",
    "突破",
    "创新高",
    "获得",
    "中标",
    "战略合作",
    "涨停",
    "大涨",
    "盈利",
    "扭亏",
    "超预期",
    "增持",
    "回购",
    "分红",
    "送转",
    "签约",
    "投产",
    "获批",
    "放量",
    "领涨",
    "龙头",
    "白马",
    "绩优",
    "朝阳",
    "景气",
    "反转",
    "矿价上涨",
    "涨价",
    "供应紧缺",
    "供不应求",
    "产能扩张",
    "库存下降",
    "需求旺盛",
    "价格上涨",
    "价格反弹",
    "资源注入",
    "储量增加",
    "品位提升",
    "满产",
    "扩产",
    "勘探突破",
    "采矿权获批",
    "营收大增",
    "利润大增",
    "毛利率提升",
    "现金流改善",
    "负债率下降",
    "降本增效",
    "订单饱满",
    "开工率提升",
    "抄底",
    "拉涨",
    "探底回升",
    "绝地反击",
    "触底反弹",
    "资金流入",
    "主力买入",
    "北向资金",
    "机构增持",
]

# 负面关键词（降级用），源自原 config.NEGATIVE_KEYWORDS
_NEGATIVE_KEYWORDS = [
    "下滑",
    "亏损",
    "违规",
    "处罚",
    "风险",
    "下跌",
    "减持",
    "跌停",
    "暴跌",
    "利空",
    "炸板",
    "退市",
    "立案",
    "调查",
    "警示",
    "冻结",
    "质押",
    "担保",
    "商誉",
    "减值",
    "预警",
    "预亏",
    "戴帽",
    "召回",
    "矿价下跌",
    "跌价",
    "供应过剩",
    "产能过剩",
    "库存积压",
    "需求疲软",
    "需求下滑",
    "价格下跌",
    "价格暴跌",
    "停产",
    "减产",
    "关停",
    "安全事故",
    "矿难",
    "品位下降",
    "资源枯竭",
    "开采成本上升",
    "营收下滑",
    "利润暴跌",
    "毛利率下降",
    "现金流紧张",
    "负债率高",
    "债务违约",
    "坏账",
    "计提减值",
    "停工",
    "裁员",
    "降薪",
    "欠薪",
    "资金流出",
    "主力卖出",
    "主力出逃",
    "资金出逃",
    "破位",
    "破发",
    "恐慌",
    "踩踏",
    "杀跌",
    "st",
    "*st",
]


class SentimentAnalyzer:
    """FinBERT2 情绪分析器（懒加载）。

    优先级：transformers(FinBERT2 本地权重) > snownlp > 关键词规则。
    首次调用 ``analyze`` 才加载模型，避免 import 时拉起 torch。
    """

    def __init__(self, model_path: Path | None = None) -> None:
        # 模型权重目录（绝对路径）；None 时跳过 transformers
        self._model_path = model_path
        self._pipeline = None
        self._loaded = False
        self._engine: str = ""  # transformers | snownlp | keyword

    @classmethod
    def from_config(cls, market: str = "a_shares") -> SentimentAnalyzer:
        """按 QuantHub 配置构造：``models_dir`` / ``modules.sentiment.model_dir``。"""
        from core.config import get_config, get_path

        cfg = get_config(market)
        model_dir = cfg.get("modules", {}).get("sentiment", {}).get("model_dir")
        if not model_dir:
            logger.warning("未配置 modules.sentiment.model_dir，将跳过 FinBERT2")
            return cls(model_path=None)
        path = get_path("models_dir", market) / model_dir
        return cls(model_path=path)

    # ------------------------------------------------------------------
    # 懒加载
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._try_load_transformers():
            self._engine = "transformers"
            return
        if self._try_load_snownlp():
            self._engine = "snownlp"
            logger.warning("FinBERT2 不可用，情绪分析降级为 snownlp")
            return
        self._engine = "keyword"
        logger.warning("transformers/snownlp 均不可用，情绪分析降级为关键词规则")

    def _try_load_transformers(self) -> bool:
        """尝试加载 FinBERT2 本地模型。"""
        if self._model_path is None or not self._model_path.is_dir():
            if self._model_path is not None:
                logger.warning("FinBERT2 模型目录不存在: %s", self._model_path)
            return False
        try:
            import torch
            from transformers import pipeline
        except ImportError:
            logger.warning("transformers/torch 未安装，跳过 FinBERT2 推理")
            return False
        try:
            # 本地模型不依赖 HF 镜像
            os.environ.pop("HF_ENDPOINT", None)
            device = 0 if torch.cuda.is_available() else -1
            self._pipeline = pipeline(
                "sentiment-analysis",
                model=str(self._model_path),
                tokenizer=str(self._model_path),
                device=device,
            )
            logger.info("FinBERT2 模型加载成功: %s", self._model_path)
            return True
        except Exception:
            logger.exception("FinBERT2 模型加载失败: %s", self._model_path)
            return False

    def _try_load_snownlp(self) -> bool:
        try:
            from snownlp import SnowNLP  # noqa: F401

            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # 推理入口
    # ------------------------------------------------------------------

    def analyze(self, text: str) -> tuple[float, float, str]:
        """分析单段文本情绪。

        Returns:
            (正向概率 0-1, 确定性 0-1, 引擎名)
        """
        if not text or len(text) < 5:
            return 0.5, 0.0, "empty"
        self._ensure_loaded()

        if self._engine == "transformers":
            score, certainty, ok = self._transformers_score(text)
            if ok:
                return score, certainty, "transformers"
        if self._engine in ("transformers", "snownlp"):
            score, ok = self._snownlp_score(text)
            if ok:
                return score, abs(score - 0.5) * 2, "snownlp"
        # 关键词降级
        score = self._keyword_score(text)
        return score, abs(score - 0.5) * 2, "keyword"

    # ------------------------------------------------------------------
    # Transformers 推理（兼容 2/3 分类，源自原 _transformers_score）
    # ------------------------------------------------------------------

    def _transformers_score(self, text: str) -> tuple[float, float, bool]:
        if self._pipeline is None:
            return 0.5, 0.0, False
        try:
            import torch
            import torch.nn.functional as F

            text_slice = text[:512]
            inputs = self._pipeline.tokenizer(
                text_slice, return_tensors="pt", truncation=True, padding=True
            ).to(self._pipeline.model.device)
            with torch.no_grad():
                logits = self._pipeline.model(**inputs).logits[0]
                probs = F.softmax(logits, dim=0).cpu().numpy()

            n_labels = len(probs)
            if n_labels == 2:
                # 2 分类：依据 id2label 判定正面索引
                pos_idx = _pick_positive_index(self._pipeline.model.config.id2label)
                pos_prob = float(probs[pos_idx])
                other = 1 - pos_idx
                logit_gap = abs(float(logits[pos_idx] - logits[other]))
                certainty = min(1.0, logit_gap / 5.0)
                return pos_prob, certainty, True
            if n_labels >= 3:
                # 3 分类（负面/中性/正面）：映射为 0 / 0.5 / 1
                pos_prob = float(probs[2] + 0.5 * probs[1])
                certainty = float(max(probs))
                return pos_prob, certainty, True
            return 0.5, 0.0, False
        except Exception:
            logger.exception("transformers 推理失败，将降级")
            return 0.5, 0.0, False

    # ------------------------------------------------------------------
    # SnowNLP 备选
    # ------------------------------------------------------------------

    def _snownlp_score(self, text: str) -> tuple[float, bool]:
        try:
            from snownlp import SnowNLP

            return float(SnowNLP(text).sentiments), True
        except Exception:
            return 0.5, False

    # ------------------------------------------------------------------
    # 关键词规则降级（源自原 _keyword_score）
    # ------------------------------------------------------------------

    def _keyword_score(self, text: str) -> float:
        """关键词规则打分，支持否定词反转与程度副词。"""
        pos_score = neg_score = 0.0
        pos_count = neg_count = 0

        for w in _POSITIVE_KEYWORDS:
            idx = text.find(w)
            if idx == -1:
                continue
            negated, intensity = self._context(text, idx)
            if negated:
                neg_score += intensity
                neg_count += 1
            else:
                pos_score += intensity
                pos_count += 1

        for w in _NEGATIVE_KEYWORDS:
            idx = text.find(w)
            if idx == -1:
                continue
            negated, intensity = self._context(text, idx)
            if negated:
                pos_score += intensity
                pos_count += 1
            else:
                neg_score += intensity
                neg_count += 1

        total = pos_count + neg_count
        if total == 0:
            return 0.5
        raw = (pos_score - neg_score) / (total + 2)
        return max(0.0, min(1.0, (raw + 1) / 2))

    @staticmethod
    def _context(text: str, idx: int) -> tuple[bool, float]:
        """检查关键词前缀是否含否定词/程度副词。"""
        negated = any(text.rfind(neg, max(0, idx - 10), idx) != -1 for neg in _NEGATION_WORDS)
        intensity = 1.0
        for adv, factor in _INTENSIFIERS.items():
            if text.rfind(adv, max(0, idx - 8), idx) != -1:
                intensity = factor
                break
        return negated, intensity


def _pick_positive_index(id2label: dict) -> int:
    """从模型 config.id2label 中识别正面标签的索引（默认 1）。"""
    for idx, lab in id2label.items():
        if str(lab).lower() in ("positive", "正面", "label_1", "1"):
            return int(idx)
    return 1
