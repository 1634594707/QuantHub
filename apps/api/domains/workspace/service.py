from __future__ import annotations

from apps.api import store

from .schemas import DEFAULT_WORKSPACES, PROFILE_LABELS


def workspace_config(user_id: str, permissions: list[str]) -> dict:
    saved = store.get_workspace_preference(user_id)
    if saved is None:
        saved = {
            "user_id": user_id,
            "profile": "stock_investor",
            "hidden_workspaces": [],
            "hidden_modules": [],
            "pinned_routes": [],
            "default_home": "/",
            "default_market": "a_shares",
            "recent_routes": [],
            "version": 0,
            "updated_at": None,
        }
    profile = saved["profile"]
    profile_workspaces = set(DEFAULT_WORKSPACES.get(profile, DEFAULT_WORKSPACES["custom"]))
    permission_workspaces = {"overview", "market", "risk", "settings"}
    if "strategy.write" in permissions:
        permission_workspaces.add("strategy")
    if "trading.write" in permissions or "simulation.write" in permissions:
        permission_workspaces.add("trading")
    visible = sorted(
        permission_workspaces.intersection(profile_workspaces)
        - set(saved.get("hidden_workspaces") or [])
    )
    # 固定入口同样必须经过权限和画像过滤，服务端返回可直接渲染的结果。
    pinned = [
        route
        for route in saved.get("pinned_routes", [])
        if route and route not in set(saved.get("hidden_modules", []))
    ]
    return {
        "ok": True,
        "profile": profile,
        "profile_label": PROFILE_LABELS.get(profile, profile),
        "available_profiles": [
            {"id": key, "label": label, "default_workspaces": DEFAULT_WORKSPACES[key]}
            for key, label in PROFILE_LABELS.items()
        ],
        "permissions": sorted(set(permissions)),
        "visible_workspaces": visible,
        "config": saved,
        "effective": {
            "workspaces": visible,
            "hidden_modules": list(saved.get("hidden_modules", [])),
            "pinned_routes": pinned,
            "default_home": saved.get("default_home", "/") if visible else "/",
            "default_market": saved.get("default_market", "a_shares"),
        },
    }
