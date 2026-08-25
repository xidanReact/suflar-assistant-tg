from suflor.matching import normalize, classify_sent

VARIANTS = [
    "Всё отлично, отдыхаю 😉 А ты как проводишь вечер?",
    "У меня всё хорошо, отдыхаю. Приятно, что спрашиваешь.",
    "Норм, отдыхаю, ничего не делаю, и у меня это отлично получается 😄",
]


def test_normalize_strips_case_punctuation_and_emoji():
    assert normalize("Привет!) 😉") == "привет"


def test_normalize_collapses_whitespace():
    assert normalize("как   дела\nвообще") == "как дела вообще"


def test_normalize_empty_for_emoji_only_message():
    assert normalize("😉😉") == ""


def test_exact_variant_is_recognized():
    source, index, ratio = classify_sent(VARIANTS[1], VARIANTS)
    assert (source, index, ratio) == ("variant", 1, 1.0)


def test_variant_recognized_despite_emoji_and_case():
    # Скопировал вариант, но убрал смайл и точку — это всё ещё он
    source, index, _ = classify_sent("всё отлично, отдыхаю А ты как проводишь вечер",
                                     VARIANTS)
    assert (source, index) == ("variant", 0)


def test_shortened_variant_counts_as_edited():
    # Отрезанный хвост — правка, а не своё сообщение. Сходство тут доходит до
    # единицы (текст целиком лежит в варианте), от точного совпадения это
    # отличает только более ранняя проверка на равенство
    source, index, ratio = classify_sent("У меня всё хорошо, отдыхаю.", VARIANTS)
    assert (source, index) == ("edited", 1)
    assert ratio >= 0.72


def test_scattered_common_words_do_not_make_an_edit():
    # Общие «а ты», «в», «как» не должны складываться в мнимую цитату
    source, _, _ = classify_sent(
        "а ты как думаешь, в среду или в пятницу лучше?", VARIANTS)
    assert source == "own"


def test_own_text_is_not_forced_onto_a_variant():
    source, index, ratio = classify_sent(
        "Слушай, а ты в эти выходные свободна? Хотел позвать в кино", VARIANTS)
    assert (source, index, ratio) == ("own", None, 0.0)


def test_short_text_never_matches_by_similarity():
    # «норм» похоже на начало третьего варианта, но это моё слово, не его
    assert classify_sent("норм", VARIANTS) == ("own", None, 0.0)


def test_short_text_still_matches_exactly():
    source, index, _ = classify_sent("Привет!", ["Привет!", "Здравствуй"])
    assert (source, index) == ("variant", 0)


def test_no_variants_means_own():
    assert classify_sent("что угодно", []) == ("own", None, 0.0)


def test_empty_text_is_own():
    assert classify_sent("   ", VARIANTS) == ("own", None, 0.0)


def test_edited_picks_the_closest_variant():
    source, index, _ = classify_sent(
        "Норм, отдыхаю, ничего не делаю, и получается отлично", VARIANTS)
    assert (source, index) == ("edited", 2)
