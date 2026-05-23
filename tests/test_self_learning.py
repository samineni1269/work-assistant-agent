import json, pytest
from pathlib import Path
from unittest.mock import patch

def test_correction_detection():
    from tools.corrections import detect_correction
    assert detect_correction("that's wrong, I meant Python not Java") == ("Python not Java", "Java")
    assert detect_correction("no, the answer is 42") == ("42", None)
    assert detect_correction("show me my emails") is None

def test_save_and_load_corrections(tmp_path):
    with patch("tools.corrections.CORRECTIONS_FILE", tmp_path / "corrections.json"):
        from tools.corrections import save_correction, get_corrections_context
        save_correction(
            bad_response="Java is the language",
            correction="Python not Java",
            user_message="what language do we use"
        )
        ctx = get_corrections_context()
        assert "Python not Java" in ctx
