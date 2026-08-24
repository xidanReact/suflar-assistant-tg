from suflor.config import (
    load_config, Config, DEFAULT_TONES, DEFAULT_STYLE, DEFAULT_MODEL,
)


def _write(tmp_path, body):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(body, encoding="utf-8")
    return str(cfg_file)


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
