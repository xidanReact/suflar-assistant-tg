import pytest

from suflor.handoff import detect

MEETING = [
    "может встретимся на выходных?",
    "давай пересечёмся в центре",
    "сходим куда-нибудь?",
    "погуляем завтра?",
    "го на свидание",
    "скинь номер, наберу",
    "давай созвонимся вечером",
    "позвони мне как освободишься",
    "напиши мне в вотсап",
    "я в whatsapp есть",
    "во сколько тебе удобно?",
    "какой у тебя адрес",
    "заеду за тобой в семь",
    "пойдём в кино в субботу?",
    "пошли гулять",
    "погнали в бар вечером",
]

ORDINARY = [
    "привет, как дела?",
    "смотрел вчера новый фильм, вообще не зашёл",
    "я на работе до шести обычно",
    "люблю кофе и долгие прогулки в наушниках",
    "увидимся!",
    "ну ты и придумал конечно",
    "работаю в поддержке, отвечаю на звонки",
    "люблю ходить в кино по выходным",
    "часто ходишь в бар?",
    "я работаю в кафе баристой",
    "сидим в кафе с подругой",
]


@pytest.mark.parametrize("text", MEETING)
def test_detects_real_world_arrangements(text):
    assert detect(text) is not None


@pytest.mark.parametrize("text", ORDINARY)
def test_ignores_ordinary_talk(text):
    assert detect(text) is None


def test_returns_the_matched_phrase_as_reason():
    # Причина уходит в пульт: «передаю тебе — созвонимся»
    assert "созвон" in detect("давай созвонимся вечером")


def test_case_and_punctuation_do_not_matter():
    assert detect("ВСТРЕТИМСЯ?!") is not None


def test_empty_text_is_safe():
    assert detect("") is None
    assert detect(None) is None
