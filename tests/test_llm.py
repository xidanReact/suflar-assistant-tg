from unittest.mock import MagicMock

import pytest

from suflor.llm import complete, LLMError


def _client(text, finish_reason="stop"):
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    choice = MagicMock(message=msg, finish_reason=finish_reason)
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


def test_returns_model_content():
    client = _client("привет")
    assert complete(client, "m", [{"role": "user", "content": "?"}],
                    0.7, 100) == "привет"


def test_passes_parameters_through():
    client = _client("ок")
    messages = [{"role": "user", "content": "?"}]
    complete(client, "deepseek-v4-pro", messages, 0.3, 555)
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-v4-pro"
    assert kwargs["messages"] is messages
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 555


def test_explains_when_reasoning_ate_the_budget():
    # V4 тратит max_tokens на рассуждения; пустой content при
    # finish_reason=length — это не поломка сети, а слишком малый лимит
    with pytest.raises(LLMError, match="увеличь лимит"):
        complete(_client("", finish_reason="length"), "m", [], 0.7, 10)


def test_wraps_api_errors():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("сеть легла")
    with pytest.raises(LLMError, match="сеть легла"):
        complete(client, "m", [], 0.7, 10)


def test_empty_content_without_length_is_returned_as_is():
    # Пустой ответ по другой причине разбирает вызывающий: у суфлёра и у
    # собеседника разные представления о том, что считать пустотой
    assert complete(_client(None), "m", [], 0.7, 10) == ""
