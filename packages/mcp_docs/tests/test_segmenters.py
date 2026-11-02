import pytest
from mcp_docs import factory
from mcp_docs.adapters.segmenter_none import NoSegmenter
from mcp_docs.adapters.segmenter_syllable_bigram import SyllableBigramSegmenter
from mcp_docs.ports import SegmenterNotConfigured, TextSegmenter
from mcp_docs.settings import Settings


def test_none_returns_text_unchanged() -> None:
    assert NoSegmenter().segment("Hợp đồng lao động") == "Hợp đồng lao động"


def test_bigram_keeps_syllables_and_adds_adjacent_pairs() -> None:
    out = SyllableBigramSegmenter().segment("Hợp đồng lao động").split()
    assert out == ["hợp", "đồng", "hợpđồng", "lao", "đồnglao", "động", "laođộng"]


def test_bigram_breaks_at_punctuation_and_newline() -> None:
    out = SyllableBigramSegmenter().segment("một, hai\nba bốn").split()
    assert "mộthai" not in out and "haiba" not in out
    assert "babốn" in out


def test_bigram_is_deterministic_and_empty_safe() -> None:
    seg = SyllableBigramSegmenter()
    assert seg.segment("a b c") == seg.segment("a b c")
    assert seg.segment("") == ""


def test_factory_registry() -> None:
    s = Settings()
    assert isinstance(factory.build_segmenter("none", s), TextSegmenter)
    assert factory.build_segmenter("syllable_bigram", s).name == "syllable_bigram"
    with pytest.raises(SegmenterNotConfigured, match="known: "):
        factory.build_segmenter("nope", s)
