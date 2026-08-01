"""DeepSeek API 批量新闻结构化增强 prompt 模板。

设计要点（从 LM Studio 改造为 DeepSeek API 可选增强）：
    - 一次调用分析 N 条新闻标题，避免 N 条 N 次调用的延迟
    - 强约束输出 JSON 数组（长度 = 输入条数）
    - entities 最多 5 个、summary ≤ 60 字、仅基于标题不得编造
    - ``News.content`` 在 akshare 抓取时为空，故 prompt 仅基于 title
    - 情绪字段由 SentimentAnalyzer 提供，API 仅负责 NER/主题/摘要（sentiment 字段保留用于校验）
"""

from __future__ import annotations

# 系统提示：要求 LLM 返回结构化 JSON 数组
# 注意：花括号需在 .format 前转义为 {{ }}，n 占位符由 build_user_prompt 注入
BATCH_ANALYSIS_SYSTEM_PROMPT = (
    "你是专业的中国 A 股财经新闻分析助手。"
    "对给定的 {n} 条新闻标题逐条做结构化分析，仅返回 JSON 数组（不要有任何额外文字、不要 markdown 代码块）：\n"
    "[\n"
    "  {{\n"
    '    "sentiment": "positive|negative|neutral",\n'
    '    "sentiment_score": -1.0 到 1.0 的浮点数（负面为负、正面为正、中性近 0），\n'
    '    "topic": "macro|monetary|industry|company|capital_action|regulation|market_mood|international",\n'
    '    "entities": [{{"text": "实体名", "type": "person|org|location"}}],\n'
    '    "summary": "不超过 60 字的中文摘要（仅基于标题，不得编造未给出的事实）",\n'
    '    "event_type": "earnings_guidance|earnings_revision|share_repurchase|shareholder_change|dividend|regulatory_penalty|major_contract|trading_status|unclassified",\n'
    '    "event_direction": "positive|negative|neutral|uncertain",\n'
    '    "event_strength": 0.0 到 1.0 的事件强度，\n'
    '    "event_confidence": 0.0 到 1.0 的抽取置信度，\n'
    '    "event_evidence": "标题中支持分类的原文片段"\n'
    "  }}, ...\n"
    "]\n"
    "硬性约束：\n"
    "1. 数组长度必须等于输入新闻条数，顺序与输入一致；\n"
    "2. entities 每条最多 5 个，type 必须是 person/org/location 之一；\n"
    '3. topic 必须是上面 8 个枚举值之一，无法判断时用 "market_mood"；\n'
    "4. sentiment 必须是 positive/negative/neutral 之一；\n"
    "5. summary 严禁出现标题中未出现的人名、数字、机构等事实；\n"
    "6. 资金净流出、撤离、主力卖出按 negative 判断；资金净流入、主力买入按 positive 判断；\n"
    "7. event_type 只能使用固定枚举；无法判断必须用 unclassified；\n"
    "8. event_direction 表示事件本身的经营或治理方向，严禁输出股价涨跌预测、目标价或买卖建议。"
)

# LLM 调用参数（参考 news_scanner._LLM_TEMPERATURE / _LLM_MAX_TOKENS）
LLM_TEMPERATURE = 0.1
# 批量 5 条 × 结构化输出，token 预算放宽到 1200（含 entities/summary）
LLM_MAX_TOKENS = 1200


def build_user_prompt(titles: list[str]) -> str:
    """构造批量分析 user prompt。

    Args:
        titles: 新闻标题列表（已去空、已截断）。

    Returns:
        直接传给 LLM 的 user message 文本。
    """
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return f"共 {len(titles)} 条新闻标题：\n{numbered}"
