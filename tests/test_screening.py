from repogen.screening import DEFAULT_RULES, screening_contract


def test_test_method_count_is_prompt_only_by_default():
    assert "test_method_count" not in {rule.name for rule in DEFAULT_RULES}
    assert "test_method_count" in screening_contract("M3_ProgramState")
