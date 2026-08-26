import pytest

from suflor.config import (
    load_config, Config, DEFAULT_TONES, DEFAULT_STYLE, DEFAULT_MODEL,
)


def _write(tmp_path, body):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(body, encoding="utf-8")
    return str(cfg_file)


def _write_config(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(str(path))


def test_reads_custom_tones_and_style(tmp_path):
    path = _write(tmp_path, "panel_chat: me\n"
                            "tones: [дерзкий, спокойный]\n"
                            "style: |\n  Пиши строчными.\n")
    cfg = load_config(path)
    assert cfg.tones == ["дерзкий", "спокойный"]
    assert cfg.style == "Пиши строчными."


def test_reads_temperature(tmp_path):
    cfg = load_config(_write(tmp_path, "panel_chat: me\ntemperature: 0.4\n"))
    assert cfg.temperature == 0.4


def test_reads_model(tmp_path):
    cfg = load_config(_write(tmp_path, "panel_chat: me\nmodel: deepseek-v4-pro\n"))
    assert cfg.model == "deepseek-v4-pro"


def test_model_falls_back_when_empty(tmp_path):
    cfg = load_config(_write(tmp_path, "panel_chat: me\nmodel: ''\n"))
    assert cfg.model == DEFAULT_MODEL


def test_tones_and_style_fall_back_when_empty(tmp_path):
    # пустой список тонов сломал бы промпт, поэтому подставляем дефолт
    path = _write(tmp_path, "panel_chat: me\ntones: []\nstyle: ''\n")
    cfg = load_config(path)
    assert cfg.tones == DEFAULT_TONES
    assert cfg.style == DEFAULT_STYLE


def test_load_config_reads_values(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "context_messages: 8\n"
        "ignore_usernames: [mom, boss]\n"
        "ignore_user_ids: [111, 222]\n"
        "panel_chat: suflor_panel\n",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_file))
    assert isinstance(cfg, Config)
    assert cfg.context_messages == 8
    assert cfg.ignore_usernames == ["mom", "boss"]
    assert cfg.ignore_user_ids == [111, 222]
    assert cfg.panel_chat == "suflor_panel"


def test_load_config_applies_defaults(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("panel_chat: suflor_panel\n", encoding="utf-8")
    cfg = load_config(str(cfg_file))
    assert cfg.context_messages == 50
    assert cfg.tones == DEFAULT_TONES
    assert cfg.style == DEFAULT_STYLE
    assert cfg.temperature == 0.7
    assert cfg.model == DEFAULT_MODEL
    assert cfg.ignore_usernames == []
    assert cfg.ignore_user_ids == []


def test_reads_about_from_the_file_next_to_the_config(tmp_path):
    (tmp_path / "about.md").write_text("Зовут Даниил, 23.\n", encoding="utf-8")
    path = _write(tmp_path, "panel_chat: me\nabout_file: about.md\n")
    assert load_config(path).about == "Зовут Даниил, 23."


def test_about_file_is_relative_to_the_config_not_the_cwd(tmp_path,
                                                          monkeypatch):
    # Бот запускают из разных мест; путь должен считаться от config.yaml
    (tmp_path / "about.md").write_text("Зовут Даниил.", encoding="utf-8")
    path = _write(tmp_path, "panel_chat: me\nabout_file: about.md\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load_config(path).about == "Зовут Даниил."


def test_about_is_empty_when_the_field_is_absent(tmp_path):
    # Конфиг, написанный до профиля, должен работать по-прежнему
    assert load_config(_write(tmp_path, "panel_chat: me\n")).about == ""


def test_missing_about_file_raises_with_the_path(tmp_path):
    # Молча работать без профиля хуже, чем упасть на старте с внятной причиной
    path = _write(tmp_path, "panel_chat: me\nabout_file: about.md\n")
    with pytest.raises(FileNotFoundError, match="about.md"):
        load_config(path)


def test_learning_defaults_when_section_is_absent(tmp_path):
    # Конфиг, написанный до самообучения, должен продолжать работать
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("panel_chat: me\n", encoding="utf-8")
    learning = load_config(str(cfg_file)).learning
    assert learning.enabled is True
    assert learning.min_samples == 5
    assert learning.outcome_window_hours == 12


def test_learning_reads_overrides(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "panel_chat: me\n"
        "learning:\n"
        "  enabled: false\n"
        "  min_samples: 20\n"
        "  train_chats: 3\n",
        encoding="utf-8")
    learning = load_config(str(cfg_file)).learning
    assert learning.enabled is False
    assert learning.min_samples == 20
    assert learning.train_chats == 3
    assert learning.style_examples == 8      # не заданное осталось дефолтным


def test_learning_ignores_unknown_keys(tmp_path):
    # Опечатка в конфиге не должна ронять запуск бота
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("panel_chat: me\nlearning:\n  min_smaples: 3\n",
                        encoding="utf-8")
    assert load_config(str(cfg_file)).learning.min_samples == 5


def test_watch_mode_defaults_to_all(tmp_path):
    # Конфиг, написанный до списка наблюдения, не должен внезапно замолчать
    cfg = load_config(_write(tmp_path, "panel_chat: me\n"))
    assert cfg.watch_mode == "all"
    assert cfg.debounce_seconds == 0.0


def test_reads_watch_mode_and_debounce(tmp_path):
    cfg = load_config(_write(tmp_path, "panel_chat: me\n"
                                       "watch_mode: selected\n"
                                       "debounce_seconds: 8\n"))
    assert cfg.watch_mode == "selected"
    assert cfg.debounce_seconds == 8.0


def test_unknown_watch_mode_raises(tmp_path):
    # Опечатка здесь — это молча замолчавший бот, неотличимый от поломки
    path = _write(tmp_path, "panel_chat: me\nwatch_mode: selectd\n")
    with pytest.raises(ValueError, match="selectd"):
        load_config(path)


def test_auto_section_is_read(tmp_path):
    cfg = _write_config(tmp_path, """
panel_chat: me
auto:
  enabled: false
  cancel_window_seconds: 30
  max_in_row: 3
  typing_simulation: false
  memory_refresh_every: 5
  recent_messages: 20
""")
    assert cfg.auto.enabled is False
    assert cfg.auto.cancel_window_seconds == 30
    assert cfg.auto.max_in_row == 3
    assert cfg.auto.typing_simulation is False
    assert cfg.auto.memory_refresh_every == 5
    assert cfg.auto.recent_messages == 20


def test_config_without_auto_section_gets_defaults(tmp_path):
    # Конфиг, написанный до этой фичи, обязан работать как раньше
    cfg = _write_config(tmp_path, "panel_chat: me\n")
    assert cfg.auto.enabled is True
    assert cfg.auto.cancel_window_seconds == 60
    assert cfg.auto.max_in_row == 10
    assert cfg.auto.recent_messages == 40


def test_unknown_auto_keys_are_ignored(tmp_path):
    # Как в learning: опечатка в ключе не должна ронять бота на старте
    cfg = _write_config(tmp_path, """
panel_chat: me
auto:
  max_in_row: 7
  какая_то_опечатка: 1
""")
    assert cfg.auto.max_in_row == 7
