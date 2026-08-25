"""FinBERT2 中文新闻情绪分析器。

从原 ``市场情绪系统`` 的 ``core/sentiment.py`` 提取核心推理逻辑，改造为
QuantHub 风格的懒加载封装：

    - 模型路径取自 core.config（``models_dir`` / ``modules.sentiment.model_dir``）
    - transformers / torch 仅在首次推理时导入，避免 import 即加载重型依赖
    - 仅使用配置的 FinBERT2 本地权重；模型不可用时显式返回不可用状态

模型权重文件 (.safetensors) 不随模块移动，运行时按上述配置路径引用；
若路径不存在、依赖缺失或推理失败，不构造替代算法结论。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """FinBERT2 情绪分析器（懒加载）。

    仅执行配置的 FinBERT2 本地权重。首次调用 ``analyze`` 才加载模型，
    避免 import 时拉起 torch；模型不可用时返回 ``(None, 0.0, "unavailable")``。
    """

    def __init__(self, model_path: Path | None = None) -> None:
        # 模型权重目录（绝对路径）；None 表示配置缺失。
        self._model_path = model_path
        self._pipeline = None
        self._loaded = False
        self._engine: str = ""  # transformers | unavailable
        self._unavailable_reason: str | None = None

    @classmethod
    def from_config(cls, market: str = "a_shares") -> SentimentAnalyzer:
        """按 QuantHub 配置构造：``models_dir`` / ``modules.sentiment.model_dir``。"""
        from core.config import get_config, get_path

        cfg = get_config(market)
        model_dir = cfg.get("modules", {}).get("sentiment", {}).get("model_dir")
        if not model_dir:
            logger.warning("未配置 modules.sentiment.model_dir，FinBERT2 不可用")
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
        self._engine = "unavailable"
        self._unavailable_reason = self._unavailable_reason or "FinBERT2 模型不可用"
        logger.warning("FinBERT2 不可用，不生成替代情绪结论: %s", self._unavailable_reason)

    @property
    def engine(self) -> str:
        """返回当前实际引擎；未加载时先检查配置模型。"""
        self._ensure_loaded()
        return self._engine

    @property
    def unavailable_reason(self) -> str | None:
        """返回模型不可用原因，供展示层与调用方记录拒绝原因。"""
        self._ensure_loaded()
        return self._unavailable_reason

    def is_available(self) -> bool:
        """只有配置的 FinBERT2 模型成功加载时才可用于研究或信号。"""
        return self.engine == "transformers"

    def _try_load_transformers(self) -> bool:
        """尝试加载 FinBERT2 本地模型。"""
        if self._model_path is None or not self._model_path.is_dir():
            if self._model_path is not None:
                logger.warning("FinBERT2 模型目录不存在: %s", self._model_path)
                self._unavailable_reason = f"FinBERT2 模型目录不存在: {self._model_path}"
            else:
                self._unavailable_reason = "未配置 FinBERT2 模型目录"
            return False
        try:
            import torch
            from transformers import pipeline
        except ImportError:
            logger.warning("transformers/torch 未安装，跳过 FinBERT2 推理")
            self._unavailable_reason = "transformers 或 torch 未安装"
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
            self._unavailable_reason = "FinBERT2 模型加载失败"
            return False

    # ------------------------------------------------------------------
    # 推理入口
    # ------------------------------------------------------------------

    def analyze(self, text: str) -> tuple[float | None, float, str]:
        """分析单段文本情绪。

        Returns:
            (正向概率 0-1 或 None, 确定性 0-1, 引擎名)。None 表示模型或输入
            不可用，调用方不得据此生成信号或研究证据。
        """
        if not text or len(text) < 5:
            return None, 0.0, "invalid_input"

        self._ensure_loaded()
        if self._engine != "transformers":
            return None, 0.0, "unavailable"
        score, certainty, ok = self._transformers_score(text)
        if ok:
            return score, certainty, "transformers"
        self._engine = "unavailable"
        self._unavailable_reason = "FinBERT2 推理失败"
        return None, 0.0, "unavailable"

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
            logger.exception("FinBERT2 推理失败")
            return 0.5, 0.0, False


def _pick_positive_index(id2label: dict) -> int:
    """从模型 config.id2label 中识别正面标签的索引（默认 1）。"""
    for idx, lab in id2label.items():
        if str(lab).lower() in ("positive", "正面", "label_1", "1"):
            return int(idx)
    return 1
