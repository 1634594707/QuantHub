"""core.viz.html_report 单测。"""

from __future__ import annotations

from core.viz.html_report import HTMLReport, _md_to_html


def _assert_basic(html: str) -> None:
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html
    assert "QuantHub" in html


def test_empty_report_renders():
    r = HTMLReport(title="空报告", theme="dark")
    h = r.to_html()
    _assert_basic(h)
    assert "空报告" in h


def test_markdown_conversion():
    out = _md_to_html("# 标题\n\n这是 **加粗** 和 *斜体*。\n\n- 项一\n- 项二")
    assert "<h1>标题</h1>" in out
    assert "<strong>加粗</strong>" in out
    assert "<em>斜体</em>" in out
    assert "<ul>" in out and "<li>项一</li>" in out


def test_blocks_and_table():
    r = HTMLReport(title="T", theme="light")
    r.add_heading("概览", 2)
    r.add_paragraph("正文。")
    r.add_card("卡片", "内容", span=2)
    r.add_table(["标的", "信号"], [["000001", "hold"], ["600519", "buy"]])
    h = r.to_html()
    _assert_basic(h)
    assert "概览" in h
    assert '<table class="tbl">' in h
    assert "<td>000001</td>" in h
    # span2 卡片
    assert 'class="card span2"' in h


def test_chart_graceful_without_plotly(monkeypatch=None):
    """plotly 缺失时图表段不应让 to_html 崩溃。"""
    r = HTMLReport(title="no-plotly", theme="dark")

    # 伪造一个没有 to_html 的对象
    class FakeFig:
        pass

    r.add_chart(FakeFig(), title="X")
    h = r.to_html()
    _assert_basic(h)
    assert "图表对象缺少 to_html" in h
    assert "cdn.plot.ly" not in h  # 无图表不应注入 plotly js


def test_save_writes_file(tmp_path):
    r = HTMLReport(title="落盘", theme="dark")
    r.add_paragraph("hello")
    p = r.save(str(tmp_path / "report.html"))
    from pathlib import Path

    assert Path(p).exists()
    assert "hello" in Path(p).read_text(encoding="utf-8")


def test_unknown_theme_raises():
    import pytest

    with pytest.raises(ValueError):
        HTMLReport(theme="neon")
