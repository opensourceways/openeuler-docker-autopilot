"""AI 服务商配置的唯一事实来源。

所有场景（新增镜像 / 自动升级 / oe 升级 / 测试脚本 / CI 修复）共用同一套
环境变量，不再各自维护模型名、provider 与 baseURL：

    AI_MODEL          模型名（provider/model），默认 gateway/deepseek-v4-pro
    AI_PROVIDER_ID    自定义 OpenAI 兼容 provider id，默认 gateway
    OPENAI_BASE_URL   模型 API 地址，默认火山引擎 API 网关
    AI_API_KEY        API Key（兼容 OPENAI_API_KEY / DEEPSEEK_API_KEY）
    AI_TIMEOUT_MS     单次 Agent 调用超时（毫秒），默认 10800000

`OPENCODE_MODEL` 保留为兼容别名：AI_MODEL 未设置时生效。
"""

from __future__ import annotations

import copy
import json
import os

DEFAULT_MODEL = "gateway/deepseek-v4-pro"
DEFAULT_PROVIDER_ID = "gateway"
DEFAULT_BASE_URL = (
    "https://st8tp3ajl0df3n8b8l8qu.apigateway-cn-beijing.volceapi.com/v1"
)
DEFAULT_TIMEOUT_MS = 10_800_000

# 与本地 opencode.jsonc 中 gateway/glm-5.3 的声明保持一致：thinking 默认开启、
# 高推理档、256k 输入。其他模型使用最小声明。
GLM_53_OPTIONS = {
    "name": "GLM-5.3",
    "maxInputTokens": 256000,
    "maxOutputTokens": 8192,
    "modalities": {
        "input": ["text"],
        "output": ["text"],
    },
    "thinking": {
        "type": "enabled",
    },
    "reasoning_effort": "high",
}

# DeepSeek V4 Pro：1M 上下文、384k 输出，支持 thinking 与 reasoning_effort，
# 推理内容通过 reasoning_content 交错返回（对齐 opencode 的模型元数据）。
DEEPSEEK_V4_PRO_OPTIONS = {
    "name": "DeepSeek V4 Pro",
    "maxInputTokens": 1000000,
    "maxOutputTokens": 384000,
    "modalities": {
        "input": ["text"],
        "output": ["text"],
    },
    "thinking": {
        "type": "enabled",
    },
    "reasoning_effort": "high",
    "interleaved": {
        "field": "reasoning_content",
    },
}

_MODEL_OPTIONS = {
    "glm-5.3": GLM_53_OPTIONS,
    "deepseek-v4-pro": DEEPSEEK_V4_PRO_OPTIONS,
}

_API_KEY_ENV_NAMES = ("AI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")


def model() -> str:
    """当前模型名；AI_MODEL 优先，OPENCODE_MODEL 作为兼容别名。"""
    return (
        os.getenv("AI_MODEL")
        or os.getenv("OPENCODE_MODEL")
        or DEFAULT_MODEL
    ).strip()


def provider_id() -> str:
    return (os.getenv("AI_PROVIDER_ID") or DEFAULT_PROVIDER_ID).strip()


def base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL).strip()


def api_key() -> str:
    """按统一优先级取 Key：AI_API_KEY → OPENAI_API_KEY → DEEPSEEK_API_KEY。"""
    for name in _API_KEY_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def timeout_ms() -> int:
    raw = os.getenv("AI_TIMEOUT_MS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_MS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_MS


def model_options(model_name: str | None = None) -> dict:
    """模型能力声明；已知模型使用完整声明，其他模型只声明名称。"""
    _, _, model_id = (model_name or model()).partition("/")
    known = _MODEL_OPTIONS.get(model_id)
    if known is not None:
        return copy.deepcopy(known)
    return {"name": model_id or model_name or ""}


def provider_config(
    model_name: str | None = None,
    *,
    base: str | None = None,
    pid: str | None = None,
) -> dict:
    """返回 opencode 的 provider 声明；不适用自定义 provider 时返回空 dict。"""
    model_name = model_name or model()
    pid = pid or provider_id()
    base = base_url() if base is None else base
    prefix, sep, model_id = model_name.partition("/")
    if not (sep and prefix == pid and model_id and base):
        return {}
    return {
        pid: {
            "npm": "@ai-sdk/openai-compatible",
            "name": "AI网关" if pid == DEFAULT_PROVIDER_ID else pid,
            "options": {
                "baseURL": base,
                "apiKey": "{env:OPENAI_API_KEY}",
            },
            "models": {model_id: model_options(model_name)},
        }
    }


def config_content(
    model_name: str | None = None,
    *,
    base: str | None = None,
    pid: str | None = None,
) -> str:
    """生成 OPENCODE_CONFIG_CONTENT；不适用时返回空串（沿用内置 provider）。"""
    provider = provider_config(model_name, base=base, pid=pid)
    if not provider:
        return ""
    return json.dumps(
        {"$schema": "https://opencode.ai/config.json", "provider": provider},
        separators=(",", ":"),
        ensure_ascii=False,
    )
