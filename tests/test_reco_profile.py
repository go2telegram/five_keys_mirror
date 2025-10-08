from app.reco import personalize_codes


def test_personalize_codes_applies_profile_preferences():
    profile = {
        "allergies": "herbs",
        "age_group": "50p",
        "lifestyle": "active",
        "season": "winter",
        "budget": "lite",
    }
    result = personalize_codes(["TEO_GREEN", "OMEGA3", "MAG_B6"], profile)
    assert "TEO_GREEN" not in result
    assert "D3" in result
    assert len(result) <= 2


def test_personalize_codes_defaults_to_unique_list():
    assert personalize_codes(["OMEGA3", "OMEGA3", "D3"], {}) == ["OMEGA3", "D3"]
