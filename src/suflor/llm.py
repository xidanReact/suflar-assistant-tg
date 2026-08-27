"""Доступ к DeepSeek: один клиент и один разбор ответа на всех.

Генераторов в проекте два — суфлёр и собеседник, — а ключ, базовый URL и
грабли у них общие. Главные грабли: V4 — рассуждающая модель, внутренние
рассуждения списываются из того же max_tokens, что и ответ. Кончился лимит
раньше ответа — приходит пустой content и finish_reason=length, что снаружи
выглядит как «модель промолчала», хотя чинится увеличением лимита.
"""
from openai import OpenAI

BASE_URL = "https://api.deepseek.com"


class LLMError(Exception):
    pass


def make_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=BASE_URL)


def complete(client, model: str, messages: list[dict], temperature: float,
             max_tokens: int) -> str:
    try:
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
            max_tokens=max_tokens)
    except Exception as e:
        raise LLMError(str(e)) from e

    choice = resp.choices[0]
    content = choice.message.content or ""
    if not content and choice.finish_reason == "length":
        raise LLMError(
            "рассуждения модели съели весь max_tokens, на ответ не "
            "осталось места — увеличь лимит")
    return content
