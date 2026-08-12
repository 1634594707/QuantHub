from apps.api.domains.portfolio import service


def test_market_breadth_accepts_quote_detail_with_error_field(monkeypatch) -> None:
    monkeypatch.setattr(service, "CONFIG", {"breadth_basket": [("600519", "消费")]})
    monkeypatch.setattr(service, "_market_fetch_disabled", lambda: False)
    monkeypatch.setattr(
        service,
        "tencent_quote_detail",
        lambda _code, _market: ("贵州茅台", 110.0, 100.0, None),
    )

    result = service.market_breadth()

    assert result["up"] == 1
    assert result["flat"] == 0
    assert result["down"] == 0
    assert result["sectors"] == [{"name": "消费", "chgPct": 10.0}]
