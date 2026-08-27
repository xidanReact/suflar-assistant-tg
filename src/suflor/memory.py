"""Память о диалоге: короткая сводка вместо простыни из сотен сообщений.

Пятьсот сырых реплик в каждом запросе размывают внимание модели — свежая
часть разговора тонет в старой, и ответ приходит «в вакууме». Сводка держит
то, что стоит помнить долго, а сырыми в промпт идут только последние реплики.

Сводка обновляется не с нуля, а дописыванием: модели дают прошлую сводку и
накопившиеся с тех пор сообщения. Так она не переписывает историю заново на
каждом шаге и не забывает то, что уже вышло за окно.
"""
from suflor import dialog, store
from suflor.llm import LLMError, complete

# Сводка едет в каждом запросе ответа — разросшаяся съедает тот самый
# контекст, ради которого затевалась
SUMMARY_MAX_CHARS = 1200

_BUDGET = 6000

_SYSTEM = (
    "Ты ведёшь заметки о переписке, чтобы потом по ним отвечать. "
    "Перепиши сводку разговора: коротко, по делу, без вступлений и "
    "оценок. Четыре раздела, каждый с новой строки:\n"
    "Собеседник: имя, возраст, город, работа, увлечения — только то, что "
    "он сам сказал в переписке.\n"
    "О чём говорили: темы, закрытые и живые.\n"
    "Как общается: тон, длина реплик, что заходит, что нет.\n"
    "Что открыто: незакрытые вопросы, обещания, к чему шёл разговор.\n"
    "Ничего не выдумывай: чего в переписке нет, того нет в сводке. "
    "Раздел, про который сказать нечего, оставь пустым. "
    f"Уложись в {SUMMARY_MAX_CHARS} символов."
)


def should_refresh(stored: dict | None, history_len: int, every: int) -> bool:
    """Пора ли обновлять сводку.

    Считаем по длине истории, а не по времени: разговор мерится репликами.
    Сводки нет вовсе — собираем сразу.
    """
    if stored is None:
        return True
    return history_len - stored["msg_count"] >= every


def build_summary_messages(history: list[dict], previous: str = "",
                           partner_name: str | None = None) -> list[dict]:
    partner = partner_name or "Собеседник"
    blocks = []
    if previous:
        blocks.append(f"Прошлая сводка:\n{previous}")
    blocks.append(f"Переписка:\n{dialog.format_history(history, partner)}")
    blocks.append("Перепиши сводку с учётом переписки.")
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


class Summarizer:
    """Собирает сводку. Температура ниже, чем у ответов: это конспект, а не
    творчество — выдумки здесь дороже сухости.
    """

    def __init__(self, client, model: str, temperature: float = 0.3):
        self._client = client
        self._model = model
        self._temperature = temperature

    def summarize(self, history: list[dict], previous: str = "",
                  partner_name: str | None = None) -> str:
        raw = complete(
            self._client, self._model,
            build_summary_messages(history, previous, partner_name),
            self._temperature, _BUDGET + 600)
        return raw.strip()[:SUMMARY_MAX_CHARS]


def refresh(conn, summarizer: Summarizer, chat_id: int, history: list[dict],
            every: int, partner_name: str | None = None) -> str:
    """Готовая сводка диалога, обновлённая, если пора.

    Ошибка модели не пробрасывается наружу: без сводки ответ хуже, но он
    есть, а без ответа бот просто молчит.
    """
    stored = store.memory(conn, chat_id)
    if not should_refresh(stored, len(history), every):
        return stored["summary"]

    previous = stored["summary"] if stored else ""
    try:
        summary = summarizer.summarize(history, previous, partner_name)
    except LLMError:
        return previous
    if not summary:
        return previous

    store.save_memory(conn, chat_id, summary, len(history))
    return summary
