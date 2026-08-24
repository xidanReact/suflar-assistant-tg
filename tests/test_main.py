from suflor.main import _ask_password


def _prompts(*values):
    seq = list(values)
    return lambda _prompt: seq.pop(0)


def test_returns_entered_password():
    assert _ask_password(_prompts("hunter2")) == "hunter2"


def test_reasks_until_non_empty(capsys):
    assert _ask_password(_prompts("", "   ", "hunter2")) == "hunter2"
    assert capsys.readouterr().out.count("не может быть пустым") == 2


def test_keeps_password_verbatim():
    # Пробелы могут быть частью пароля — обрезать нельзя, они только
    # не считаются за непустой ввод.
    assert _ask_password(_prompts(" hunter2 ")) == " hunter2 "
