import re
from datetime import datetime

from suflor.dialog import (
    format_history, elapsed_since_last, initiative_summary, questions_asked,
    facts_rules, plural, variants_word, times_word, humanize_delta,
)
from suflor.llm import LLMError, make_client, complete

_NUMBERED = re.compile(r"^\d+[)\].:-]\s*(.+)$")

# Модель любит начинать разбор с заголовка «Краткий разбор:» — он лишний
_ANALYSIS_LABEL = re.compile(
    r"^\**(краткий|короткий)?\s*разбор( диалога)?\**\s*:\s*", re.IGNORECASE)

# Замерено на deepseek-v4-flash и -pro: рассуждения занимают 1900–3900 токенов
_REASONING_BUDGET = 6000

# Имя, под которым ошибку ловит main и тесты: снаружи это по-прежнему
# «суфлёр не смог», внутри — общая ошибка обращения к модели
SuggesterError = LLMError


def build_system_prompt(tones: list[str], style: str,
                        style_block: str = "", about: str = "") -> str:
    """Системный промпт из настроек: тона и манера письма задаются в конфиге,
    структура ответа (разбор + нумерованные варианты) — нет, её парсим.

    style_block — выученная манера из profile.py. Идёт после стиля из конфига
    и объявлен важнее него, но структуру ответа и потолок флирта не отменяет:
    они стоят до него и сформулированы как запреты.

    about — факты обо мне из config.about. Он не дополняет запрет
    выдумывать, а заменяет его: держать рядом «фактов не выдумывай» и
    «мелочь придумать можно» — значит оставить модели выбор, какое из
    двух правил важнее.
    """
    n = len(tones)
    numbered = ", ".join(f"{i + 1}) {t}" for i, t in enumerate(tones))
    # Пустой профиль обязан давать ровно тот же промпт, что и раньше
    learned = f"\n\n{style_block}\n\n" if style_block else " "
    facts = facts_rules(about)
    return (
        "Ты помогаешь мне вести переписку на сайте знакомств. "
        "Сначала дай краткий разбор диалога: 2-3 строки о том, как идёт "
        "общение, какой тон у собеседника и что стоит учесть. "
        "Разбор — без нумерации. "
        "Обязательно скажи про инициативу: кто начал переписку и кто её "
        "тянет. Данные об этом посчитаны за тебя и даны блоком «Инициатива в "
        "диалоге» после переписки — опирайся на них, не пересчитывай сам. "
        "Если первым написал собеседник или он сам возвращается после пауз — "
        "интерес есть, можно отвечать теплее и свободнее. Если переписку "
        "начал и тяну я, а в ответ идут короткие реплики без встречных "
        "вопросов — не дави: пиши короче и легче, дай собеседнику место. "
        "Если начало переписки не видно, про то, кто написал первым, не "
        "говори — суди только по тому, кто её тянет сейчас. "
        f"Затем предложи РОВНО {n} {variants_word(n)} моего следующего "
        f"сообщения, каждый своим тоном: {numbered}. "
        "Если последним в диалоге писал я и переписка заглохла — предлагай, "
        "как её оживить, а не отвечай сам себе. "
        "Чувствуй момент: в переписке отмечены паузы между сообщениями и "
        "указано, сколько времени прошло с последнего. Ответ через пять минут "
        "и ответ через три дня звучат по-разному — во втором случае неуместно "
        "продолжать фразу как ни в чём не бывало, но и извиняться за молчание "
        "не нужно, если пауза небольшая. Учитывай время суток, если оно видно "
        "по переписке. "
        "Не ходи по кругу. После переписки дан список уже прозвучавших "
        "вопросов — своих и чужих. Не задавай их заново. Главное: не возвращай "
        "собеседнику вопрос, который он сам только что задал мне — на «чем "
        "занимаешься?» надо ответить, а не переспросить «а ты чем "
        "занимаешься?». Отбить вопрос обратно («а ты?», «а у тебя?») можно "
        "только тогда, когда на него в переписке ещё никто не отвечал. "
        "Ответил — двигай разговор дальше: новая тема, деталь о себе, новый "
        "вопрос. Вопрос вообще не обязателен в каждом сообщении, живая реплика "
        "без него лучше дежурного «а ты?». "
        "Список вопросов сверяй по смыслу, а не по буквам: переформулировка "
        "того, на что уже ответили, — тот же повтор. «Как дела?» и «как прошёл "
        "день?», «чем занимаешься?» и «чем занят сейчас?», «как выходные?» и "
        "«как провёл выходные?» — это одно и то же, второй раз спрашивать "
        "нельзя. Хочешь спросить о том же — иди вглубь конкретной детали, "
        "которую собеседник уже назвал, а не заходи на тот же круг заново. "
        f"{facts}"
        "Не всё в переписке — текст. Медиа помечено в квадратных скобках: "
        "[фото], [стикер 😂], [кружок 15 сек], [голосовое 12 сек] и дальше "
        "расшифровка. Голосовое — это голос, а не набранное сообщение: "
        "учитывай это, отвечая. Если стоит «не расшифровано», содержимого "
        "не знает никто — не делай вид, что знаешь, о чём там речь. Тогда "
        "отвечай на сам факт голосового или на то, о чём говорили до него. "
        "Не переигрывай. Никакого пафоса, наигранного остроумия, заготовок в "
        "духе пикап-фраз, нагромождения шуток и метафор. Одна мысль на "
        "сообщение. Лучше проще и живее, чем эффектнее. "
        "Флирт держи лёгким: тепло и интерес — да, пошлый подтекст — нет. Без "
        "двусмысленностей, намёков на секс и разговоров про тело и внешность "
        "в откровенном ключе. Если собеседник сам шутит на грани, можно "
        "ответить в тон, но не подхватывать и не усиливать. "
        "Каждый вариант — одна-две короткие фразы, как реально пишут в "
        "мессенджере, а не абзац. "
        f"{style}{learned}"
        "Каждый вариант — на отдельной строке в формате '1) текст', "
        "'2) текст', без лишних пояснений."
    )


def build_messages(history: list[dict], system_prompt: str,
                   now: datetime | None = None,
                   partner_name: str | None = None,
                   full_history: bool = True) -> list[dict]:
    """Диалог для модели: реплики, заметные паузы между ними, время,
    прошедшее с последнего сообщения, и сводка по инициативе.
    """
    partner = partner_name or "Собеседник"
    dialog_text = format_history(history, partner)
    elapsed = elapsed_since_last(history, now)
    since = f"\n\nС последнего сообщения прошло: {elapsed}." if elapsed else ""
    blocks = "".join(
        f"\n\n{block}" for block in
        (initiative_summary(history, partner, full_history),
         questions_asked(history, partner)) if block)
    user = (f"Вот переписка:\n{dialog_text}{since}{blocks}"
            "\n\nДай варианты моего ответа.")
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def parse_suggestions(raw: str) -> list[str]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _NUMBERED.match(line)
        if m:
            out.append(m.group(1).strip())
    return out


def parse_analysis(raw: str) -> str:
    """Всё до первого пронумерованного варианта — это разбор диалога."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if _NUMBERED.match(line):
            break
        if line:
            lines.append(line)
    return _ANALYSIS_LABEL.sub("", " ".join(lines)).strip()


class Suggester:
    def __init__(self, api_key: str | None = None, tones: list[str] = None,
                 style: str = "", temperature: float = 0.7,
                 model: str = "deepseek-v4-pro", about: str = "",
                 client=None):
        self._client = client or make_client(api_key)
        self._model = model
        self._tones = tones
        self._style = style
        self._about = about
        # Промпт без выученной манеры постоянен, поэтому собирается один раз:
        # факты обо мне читаются на старте и в течение работы не меняются
        self._system_prompt = build_system_prompt(tones, style, about=about)
        self._temperature = temperature
        # DeepSeek V4 — рассуждающие модели: внутренние рассуждения списываются
        # из того же max_tokens, что и ответ, и съедают несколько тысяч токенов.
        # Без запаса поверх них content приходит пустым, а finish_reason=length.
        self._max_tokens = _REASONING_BUDGET + 500 * len(tones)

    def _complete(self, system_prompt: str, history: list[dict],
                  max_tokens: int, partner_name: str | None = None,
                  full_history: bool = True) -> str:
        return complete(
            self._client, self._model,
            build_messages(history, system_prompt, partner_name=partner_name,
                           full_history=full_history),
            self._temperature, max_tokens)

    def analyze(self, history: list[dict],
                partner_name: str | None = None,
                full_history: bool = True,
                style_block: str = "") -> tuple[str, list[str]]:
        """Разбор диалога плюс варианты следующего сообщения.

        full_history=False — переписка обрезана лимитом контекста, начало не
        видно: тогда о том, кто написал первым, судить нельзя.
        style_block — выученная манера письма, пустая строка до накопления
        данных.
        """
        prompt = self._system_prompt
        if style_block:
            prompt = build_system_prompt(self._tones, self._style,
                                         style_block, self._about)
        raw = self._complete(prompt, history, self._max_tokens,
                             partner_name, full_history)
        variants = parse_suggestions(raw)
        if not variants:
            raise SuggesterError("модель вернула пустой/неразборчивый ответ")
        return parse_analysis(raw), variants
