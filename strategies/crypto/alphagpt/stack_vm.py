# -*- coding: utf-8 -*-
"""StackVM 公式 DSL — 从 AlphaGPT/model_core 逐字移植。

合并原 ``vm.py`` + ``ops.py`` + ``vocab.py`` 三件套，保持指令集与执行逻辑
**逐字不变**：
    - ``OPS_CONFIG``     : 指令集（名称 / 实现 / arity），逐字保留自 ops.py
    - ``FORMULA_VOCAB``  : 因子词表（特征名 + 算子名），逐字保留自 vocab.py
    - ``StackVM``        : 栈式公式虚拟机，执行逻辑逐字保留自 vm.py

torch 为重依赖：本模块在模块级 ``import torch``，但由 ``strategy.py``
**懒加载**（仅在 produce/backtest 时才 import 本模块），故策略包导入不触发
torch，避免未装 torch 时导入失败。
"""
from __future__ import annotations

from dataclasses import dataclass

import torch


# ===== 以下为原 ops.py 逐字移植（指令集定义） =====
@torch.jit.script
def _ts_delay(x: torch.Tensor, d: int) -> torch.Tensor:
    if d == 0: return x
    pad = torch.zeros((x.shape[0], d), device=x.device)
    return torch.cat([pad, x[:, :-d]], dim=1)

@torch.jit.script
def _op_gate(condition: torch.Tensor, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    mask = (condition > 0).float()
    return mask * x + (1.0 - mask) * y

@torch.jit.script
def _op_jump(x: torch.Tensor) -> torch.Tensor:
    mean = x.mean(dim=1, keepdim=True)
    std = x.std(dim=1, keepdim=True) + 1e-6
    z = (x - mean) / std
    return torch.relu(z - 3.0)

@torch.jit.script
def _op_decay(x: torch.Tensor) -> torch.Tensor:
    return x + 0.8 * _ts_delay(x, 1) + 0.6 * _ts_delay(x, 2)

OPS_CONFIG = [
    ('ADD', lambda x, y: x + y, 2),
    ('SUB', lambda x, y: x - y, 2),
    ('MUL', lambda x, y: x * y, 2),
    ('DIV', lambda x, y: x / (y + 1e-6), 2),
    ('NEG', lambda x: -x, 1),
    ('ABS', torch.abs, 1),
    ('SIGN', torch.sign, 1),
    ('GATE', _op_gate, 3),
    ('JUMP', _op_jump, 1),
    ('DECAY', _op_decay, 1),
    ('DELAY1', lambda x: _ts_delay(x, 1), 1),
    ('MAX3', lambda x: torch.max(x, torch.max(_ts_delay(x,1), _ts_delay(x,2))), 1)
]


# ===== 以下为原 vocab.py 逐字移植（因子词表） =====
FEATURE_NAMES = (
    "RET",
    "LIQ_SCORE",
    "PRESSURE",
    "FOMO",
    "DEV",
    "LOG_VOL",
)


@dataclass(frozen=True)
class FormulaVocab:
    feature_names: tuple[str, ...]
    operator_names: tuple[str, ...]

    @property
    def feature_count(self) -> int:
        return len(self.feature_names)

    @property
    def operator_offset(self) -> int:
        return self.feature_count

    @property
    def token_names(self) -> tuple[str, ...]:
        return self.feature_names + self.operator_names

    @property
    def size(self) -> int:
        return len(self.token_names)


FORMULA_VOCAB = FormulaVocab(
    feature_names=FEATURE_NAMES,
    operator_names=tuple(cfg[0] for cfg in OPS_CONFIG),
)


# ===== 以下为原 vm.py 逐字移植（栈式公式虚拟机） =====
class StackVM:
    def __init__(self):
        self.feat_offset = FORMULA_VOCAB.operator_offset
        self.op_map = {i + self.feat_offset: cfg[1] for i, cfg in enumerate(OPS_CONFIG)}
        self.arity_map = {i + self.feat_offset: cfg[2] for i, cfg in enumerate(OPS_CONFIG)}

    def execute(self, formula_tokens, feat_tensor):
        stack = []
        try:
            for token in formula_tokens:
                token = int(token)
                if token < self.feat_offset:
                    if token >= feat_tensor.shape[1]:
                        return None
                    stack.append(feat_tensor[:, token, :])
                elif token in self.op_map:
                    arity = self.arity_map[token]
                    if len(stack) < arity: return None
                    args = []
                    for _ in range(arity):
                        args.append(stack.pop())
                    args.reverse()
                    func = self.op_map[token]
                    res = func(*args)
                    if torch.isnan(res).any() or torch.isinf(res).any():
                        res = torch.nan_to_num(res, nan=0.0, posinf=1.0, neginf=-1.0)
                    stack.append(res)
                else:
                    return None
            if len(stack) == 1:
                return stack[0]
            else:
                return None
        except Exception:
            return None
