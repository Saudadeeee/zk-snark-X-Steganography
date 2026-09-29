from __future__ import annotations

from src.bitstream import cavlc


def test_encoder_vlc_lookup_reuses_bounded_immutable_results(monkeypatch) -> None:
    for lookup in (
        cavlc.find_coeff_token_code,
        cavlc.find_total_zeros_code,
        cavlc.find_run_before_code,
    ):
        if hasattr(lookup, "cache_clear"):
            lookup.cache_clear()

    calls = {"coeff": 0, "zeros": 0, "run": 0}
    original_coeff = cavlc.build_reverse_coeff_token_table
    original_zeros = cavlc.build_reverse_total_zeros_table
    original_run = cavlc.build_reverse_run_before_table

    def count_coeff(*args, **kwargs):
        calls["coeff"] += 1
        return original_coeff(*args, **kwargs)

    def count_zeros(*args, **kwargs):
        calls["zeros"] += 1
        return original_zeros(*args, **kwargs)

    def count_run(*args, **kwargs):
        calls["run"] += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(cavlc, "build_reverse_coeff_token_table", count_coeff)
    monkeypatch.setattr(cavlc, "build_reverse_total_zeros_table", count_zeros)
    monkeypatch.setattr(cavlc, "build_reverse_run_before_table", count_run)

    coeff_first = cavlc.find_coeff_token_code(1, 0, 0)
    zero_first = cavlc.find_total_zeros_code(0, 1)
    run_first = cavlc.find_run_before_code(0, 1)
    assert cavlc.find_coeff_token_code(1, 0, 0) == coeff_first
    assert cavlc.find_total_zeros_code(0, 1) == zero_first
    assert cavlc.find_run_before_code(0, 1) == run_first

    assert calls == {"coeff": 1, "zeros": 1, "run": 1}
