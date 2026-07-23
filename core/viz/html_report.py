# -*- coding: utf-8 -*-
"""自包含 HTML 报告生成器（不依赖 Streamlit，可落盘 / 邮件 / 企微）。

设计目标：把"HTML 报告"作为底座通用能力，而不是每个策略各写一套。
任何策略只要拿到结构化数据（Signal / 表格 / 文本 / Plotly Figure），
就能拼出一份单文件、可归档、可转发的 HTML 报告。

特性：
    - 栈式 builder 接口（add_heading / add_paragraph / add_markdown /
      add_card / add_table / add_chart / add_raw）
    - 内置轻量 Markdown → HTML 转换（仅 stdlib，无外部依赖）
    - 暗色 / 亮色双主题（默认暗色，契合全局暗色偏好）
    - Plotly 图表可选 CDN 或 inline 嵌入；plotly 缺失时图表段优雅跳过
    - 输出单文件 HTML，自带样式，可离线打开（CDN 模式需联网渲染图表）
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime
from typing import Any, Iterable, Optional

# Plotly.js CDN（按需替换为内联以彻底离线）
PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# ---------------------------------------------------------------------------
# 主题
# ---------------------------------------------------------------------------
_THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0B1018",
        "panel": "#141B26",
        "panel2": "#1B2433",
        "text": "#E6EDF3",
        "muted": "#8B98A9",
        "border": "#263041",
        "accent": "#2E86AB",
        "up": "#E63946",      # A股习惯：涨红
        "down": "#06A77D",    # 跌绿
        "shadow": "0 2px 8px rgba(0,0,0,0.4)",
    },
    "light": {
        "bg": "#F5F7FA",
        "panel": "#FFFFFF",
        "panel2": "#EEF2F7",
        "text": "#1A2230",
        "muted": "#5B6878",
        "border": "#E1E7EF",
        "accent": "#2E86AB",
        "up": "#E63946",
        "down": "#06A77D",
        "shadow": "0 2px 8px rgba(0,0,0,0.08)",
    },
}


# ---------------------------------------------------------------------------
# Markdown（极简）转换
# ---------------------------------------------------------------------------
def _md_to_html(md: str) -> str:
    """把常见 Markdown 片段转为 HTML（标题 / 加粗 / 斜体 / 列表 / 行内代码 / 分段）。

    仅覆盖报告中常用的子集，不引入 markdown 依赖。
    """
    if not md:
        return ""
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    in_list = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            i += 1
            continue
        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        # 无序列表
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue
        # 普通段落
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{_inline(stripped)}</p>")
        i += 1
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline(text: str) -> str:
    """行内：加粗 / 斜体 / 行内代码。"""
    text = _html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


# ---------------------------------------------------------------------------
# 报告构建器
# ---------------------------------------------------------------------------
class HTMLReport:
    """栈式 HTML 报告构建器。

    用法::

        r = HTMLReport(title="晨会简报", theme="dark")
        r.add_heading("今日概览", 2)
        r.add_markdown("**沪深300** 震荡收平，情绪中性。")
        r.add_card("北向资金", "净流入 +12.3 亿")
        r.add_table(["标的", "信号", "评分"], [["000001", "hold", "0.5"]])
        r.add_chart(fig)  # plotly Figure
        html_str = r.to_html()
        r.save("report.html")
    """

    def __init__(self, title: str = "QuantHub 报告", theme: str = "dark",
                 plotly_cdn: bool = True) -> None:
        if theme not in _THEMES:
            raise ValueError(f"未知主题 {theme!r}，可选: {list(_THEMES)}")
        self.title = title
        self.theme = theme
        self._t = _THEMES[theme]
        self._plotly_cdn = plotly_cdn
        self._blocks: list[str] = []
        self._charts: list[str] = []   # 需内联 plotly.js 时集中放置
        self._plotly_inlined = False

    # -- 内容块 ----------------------------------------------------------
    def add_raw(self, html: str) -> "HTMLReport":
        self._blocks.append(html)
        return self

    def add_heading(self, text: str, level: int = 2) -> "HTMLReport":
        lvl = max(1, min(4, level))
        self._blocks.append(f"<h{lvl} class='h{lvl}'>{_html.escape(text)}</h{lvl}>")
        return self

    def add_paragraph(self, text: str) -> "HTMLReport":
        self._blocks.append(f"<p>{_html.escape(text)}</p>")
        return self

    def add_markdown(self, md: str) -> "HTMLReport":
        self._blocks.append(_md_to_html(md))
        return self

    def add_card(self, title: str, body: str, span: int = 1) -> "HTMLReport":
        """单卡片。body 可为 HTML 片段；span 1/2 控制网格占位。"""
        cls = "card" if span == 1 else "card span2"
        self._blocks.append(
            f'<div class="{cls}"><div class="card-title">{_html.escape(title)}</div>'
            f'<div class="card-body">{body}</div></div>'
        )
        return self

    def add_table(self, headers: Iterable[str], rows: Iterable[Iterable[Any]],
                  cls: str = "tbl") -> "HTMLReport":
        th = "".join(f"<th>{_html.escape(str(h))}</th>" for h in headers)
        body_rows = []
        for row in rows:
            tds = "".join(f"<td>{_html.escape(str(c))}</td>" for c in row)
            body_rows.append(f"<tr>{tds}</tr>")
        table = (
            f'<table class="{cls}"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table>'
        )
        self._blocks.append(table)
        return self

    def add_chart(self, fig: Any, title: Optional[str] = None) -> "HTMLReport":
        """嵌入一个 Plotly Figure。fig 需有 to_html 方法。

        plotly 缺失或 fig 非法时，输出占位提示而非崩溃。
        """
        try:
            to_html = getattr(fig, "to_html", None)
            if to_html is None:
                self._blocks.append(
                    '<div class="chart-na">⚠️ 图表对象缺少 to_html 方法，已跳过</div>'
                )
                return self
            fig_html = to_html(full_html=False, include_plotlyjs=False,
                               config={"responsive": True})
        except Exception as exc:  # pragma: no cover - 防御性
            self._blocks.append(
                f'<div class="chart-na">⚠️ 图表渲染失败：{_html.escape(str(exc))}</div>'
            )
            return self
        block = ""
        if title:
            block += f'<div class="chart-title">{_html.escape(title)}</div>'
        block += f'<div class="chart-card">{fig_html}</div>'
        self._blocks.append(block)
        # 记录需要 plotly.js 的地方（inline 模式下统一在 </body> 前注入）
        self._charts.append(fig_html)
        return self

    # -- 输出 ------------------------------------------------------------
    def to_html(self) -> str:
        t = self._t
        blocks = "\n".join(self._blocks)
        # plotly.js 注入方式
        if self._charts:
            if self._plotly_cdn:
                plotly_tag = f'<script src="{PLOTLY_CDN}" charset="utf-8"></script>'
            else:
                plotly_tag = _inline_plotly_js()
        else:
            plotly_tag = ""
        css = _CSS.format(**t)
        generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return _PAGE.format(
            title=_html.escape(self.title),
            css=css,
            plotly=plotly_tag,
            blocks=blocks,
            generated=generated,
            theme=self.theme,
        )

    def save(self, path: str) -> str:
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_html(), encoding="utf-8")
        return str(p)


def _inline_plotly_js() -> str:
    """尝试读取本地 plotly 包内嵌的 min.js；失败则回退 CDN。"""
    try:
        import plotly
        from pathlib import Path
        cand = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
        if cand.exists():
            return f'<script>{cand.read_text(encoding="utf-8")}</script>'
    except Exception:
        pass
    return f'<script src="{PLOTLY_CDN}" charset="utf-8"></script>'


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------
_CSS = """
:root {{
  --bg:{bg}; --panel:{panel}; --panel2:{panel2}; --text:{text};
  --muted:{muted}; --border:{border}; --accent:{accent};
  --up:{up}; --down:{down}; --shadow:{shadow};
}}
* {{ box-sizing: border-box; }}
body {{
  margin:0; background:var(--bg); color:var(--text);
  font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
  line-height:1.6; padding:28px; font-size:14px;
}}
.wrap {{ max-width:1080px; margin:0 auto; }}
h1 {{ font-size:24px; margin:0 0 4px; }}
.subtitle {{ color:var(--muted); font-size:12px; margin-bottom:20px; }}
h2 {{ font-size:19px; margin:24px 0 10px; border-left:3px solid var(--accent); padding-left:10px; }}
h3 {{ font-size:16px; margin:18px 0 8px; }}
h4 {{ font-size:14px; margin:14px 0 6px; color:var(--muted); }}
p {{ margin:8px 0; }}
code {{ background:var(--panel2); padding:1px 5px; border-radius:4px; font-size:12px; }}
ul {{ margin:8px 0; padding-left:22px; }}
.grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:14px; margin:14px 0; }}
.card {{ background:var(--panel); border:1px solid var(--border); border-radius:10px;
        padding:14px 16px; box-shadow:var(--shadow); }}
.card.span2 {{ grid-column:1 / -1; }}
.card-title {{ font-size:13px; color:var(--muted); margin-bottom:6px; font-weight:600; }}
.card-body {{ font-size:14px; }}
.tbl {{ width:100%; border-collapse:collapse; margin:12px 0;
        background:var(--panel); border-radius:8px; overflow:hidden; }}
.tbl th, .tbl td {{ border:1px solid var(--border); padding:8px 12px; text-align:left; font-size:13px; }}
.tbl th {{ background:var(--panel2); color:var(--muted); font-weight:600; }}
.chart-card {{ background:var(--panel); border:1px solid var(--border); border-radius:10px;
              padding:10px; margin:12px 0; box-shadow:var(--shadow); }}
.chart-title {{ font-size:13px; color:var(--muted); margin-bottom:6px; font-weight:600; }}
.chart-na {{ color:var(--muted); font-style:italic; padding:8px 0; }}
.up {{ color:var(--up); }} .down {{ color:var(--down); }}
footer {{ margin-top:30px; color:var(--muted); font-size:11px; text-align:center; }}
"""

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="{theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
{plotly}
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <div class="subtitle">生成于 {generated} · QuantHub</div>
  <div class="content">
{blocks}
  </div>
  <footer>QuantHub · 自包含 HTML 报告（{theme} 主题）</footer>
</div>
</body>
</html>
"""
