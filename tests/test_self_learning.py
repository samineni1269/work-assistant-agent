import json, pytest
from pathlib import Path
from unittest.mock import patch

def test_correction_detection():
    from tools.corrections import detect_correction
    assert detect_correction("that's wrong, I meant Python not Java") == ("Python not Java", "Java")
    assert detect_correction("no, the answer is 42") == ("42", None)
    assert detect_correction("show me my emails") is None

def test_save_and_load_corrections(tmp_path):
    import tools.corrections as mod
    from unittest.mock import patch
    with patch.object(mod, "CORRECTIONS_FILE", tmp_path / "corrections.json"):
        mod.save_correction(
            bad_response="Java is the language",
            correction="Python not Java",
            user_message="what language do we use"
        )
        ctx = mod.get_corrections_context()
        assert "Python not Java" in ctx
        assert "Past corrections" in ctx
