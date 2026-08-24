from suflor.config import load_config, Config


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
    assert cfg.ignore_usernames == []
    assert cfg.ignore_user_ids == []
