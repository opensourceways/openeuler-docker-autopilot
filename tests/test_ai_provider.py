import json

from scripts.lib import ai_provider


def _clear(monkeypatch):
    for name in (
        "AI_MODEL",
        "OPENCODE_MODEL",
        "AI_PROVIDER_ID",
        "OPENAI_BASE_URL",
        "AI_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "AI_TIMEOUT_MS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_one_gateway_contract(monkeypatch):
    _clear(monkeypatch)

    assert ai_provider.model() == "gateway/deepseek-v4-pro"
    assert ai_provider.provider_id() == "gateway"
    assert ai_provider.base_url() == ai_provider.DEFAULT_BASE_URL
    assert ai_provider.timeout_ms() == 10_800_000
    assert ai_provider.api_key() == ""


def test_model_and_provider_can_be_overridden(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AI_MODEL", "gateway/other-model")
    monkeypatch.setenv("AI_PROVIDER_ID", "custom")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")

    assert ai_provider.model() == "gateway/other-model"
    assert ai_provider.provider_id() == "custom"
    assert ai_provider.base_url() == "https://example.test/v1"


def test_opencode_model_is_a_backward_compatible_alias(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENCODE_MODEL", "gateway/legacy")

    assert ai_provider.model() == "gateway/legacy"


def test_api_key_precedence_is_ai_then_openai_then_deepseek(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    assert ai_provider.api_key() == "deepseek-key"

    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    assert ai_provider.api_key() == "openai-key"

    monkeypatch.setenv("AI_API_KEY", "ai-key")
    assert ai_provider.api_key() == "ai-key"


def test_config_content_declares_the_custom_provider(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AI_MODEL", "gateway/glm-5.3")

    config = json.loads(ai_provider.config_content())

    gateway = config["provider"]["gateway"]
    assert gateway["npm"] == "@ai-sdk/openai-compatible"
    assert gateway["options"]["baseURL"] == ai_provider.DEFAULT_BASE_URL
    assert gateway["options"]["apiKey"] == "{env:OPENAI_API_KEY}"
    assert gateway["models"]["glm-5.3"]["maxInputTokens"] == 256000


def test_deepseek_v4_pro_has_a_full_capability_declaration(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AI_MODEL", "gateway/deepseek-v4-pro")

    config = json.loads(ai_provider.config_content())
    model = config["provider"]["gateway"]["models"]["deepseek-v4-pro"]

    assert model["name"] == "DeepSeek V4 Pro"
    assert model["maxInputTokens"] == 1_000_000
    assert model["maxOutputTokens"] == 384_000
    assert model["thinking"] == {"type": "enabled"}
    assert model["reasoning_effort"] == "high"
    assert model["interleaved"] == {"field": "reasoning_content"}
    assert model["modalities"] == {"input": ["text"], "output": ["text"]}


def test_unknown_model_gets_only_a_name_declaration(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AI_MODEL", "gateway/qwen3.7-max")

    config = json.loads(ai_provider.config_content())
    model = config["provider"]["gateway"]["models"]["qwen3.7-max"]

    assert model == {"name": "qwen3.7-max"}


def test_config_content_skips_builtin_or_unprefixed_models(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AI_MODEL", "deepseek/deepseek-chat")
    assert ai_provider.config_content() == ""

    monkeypatch.setenv("AI_MODEL", "glm-5.3")
    assert ai_provider.config_content() == ""


def test_config_content_skips_missing_base_url(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", " ")

    assert ai_provider.config_content() == ""


def test_timeout_falls_back_on_invalid_value(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AI_TIMEOUT_MS", "not-a-number")
    assert ai_provider.timeout_ms() == 10_800_000

    monkeypatch.setenv("AI_TIMEOUT_MS", "9000")
    assert ai_provider.timeout_ms() == 9000
