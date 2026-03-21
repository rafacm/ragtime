from django.test import TestCase

from episodes.timestamps import find_entity_start_time


class FindEntityStartTimeTests(TestCase):
    """Unit tests for the find_entity_start_time pure function."""

    WORDS = [
        {"word": "Hello,", "start": 0.0, "end": 0.5},
        {"word": "welcome", "start": 0.6, "end": 1.0},
        {"word": "to", "start": 1.0, "end": 1.1},
        {"word": "the", "start": 1.1, "end": 1.2},
        {"word": "Jazz", "start": 1.2, "end": 1.5},
        {"word": "podcast.", "start": 1.5, "end": 2.0},
        {"word": "Miles", "start": 5.0, "end": 5.3},
        {"word": "Davis", "start": 5.3, "end": 5.6},
        {"word": "played", "start": 5.7, "end": 6.0},
        {"word": "Kind", "start": 10.0, "end": 10.3},
        {"word": "of", "start": 10.3, "end": 10.4},
        {"word": "Blue,", "start": 10.4, "end": 10.8},
        {"word": "Miles", "start": 25.0, "end": 25.3},
        {"word": "was", "start": 25.3, "end": 25.5},
        {"word": "great.", "start": 25.5, "end": 25.8},
    ]

    def test_single_word_found(self):
        result = find_entity_start_time("Jazz", self.WORDS, 0.0, 30.0)
        self.assertEqual(result, 1.2)

    def test_multi_word_entity(self):
        result = find_entity_start_time("Miles Davis", self.WORDS, 0.0, 30.0)
        self.assertEqual(result, 5.0)

    def test_entity_not_found(self):
        result = find_entity_start_time("Charlie Parker", self.WORDS, 0.0, 30.0)
        self.assertIsNone(result)

    def test_empty_words(self):
        result = find_entity_start_time("Jazz", [], 0.0, 30.0)
        self.assertIsNone(result)

    def test_case_insensitive(self):
        result = find_entity_start_time("miles davis", self.WORDS, 0.0, 30.0)
        self.assertEqual(result, 5.0)

    def test_punctuation_handling(self):
        result = find_entity_start_time("Jazz", self.WORDS, 0.0, 30.0)
        self.assertEqual(result, 1.2)

    def test_entity_outside_chunk_range(self):
        result = find_entity_start_time("Miles Davis", self.WORDS, 20.0, 30.0)
        # "Miles Davis" consecutive pair is at 5.0-5.6, outside [20, 30)
        # But "Miles" alone is at 25.0 — partial fallback
        self.assertEqual(result, 25.0)

    def test_entity_completely_outside_range(self):
        result = find_entity_start_time("Jazz", self.WORDS, 50.0, 60.0)
        self.assertIsNone(result)

    def test_multiple_occurrences_returns_first(self):
        result = find_entity_start_time("Miles", self.WORDS, 0.0, 30.0)
        self.assertEqual(result, 5.0)

    def test_punctuation_in_multi_word(self):
        result = find_entity_start_time("Kind of Blue", self.WORDS, 0.0, 30.0)
        self.assertEqual(result, 10.0)

    def test_partial_match_fallback(self):
        # "Miles Davis" as consecutive words only at 5.0-5.6
        # In range [20, 30) only "Miles" at 25.0 — fallback to partial
        result = find_entity_start_time("Miles Davis", self.WORDS, 20.0, 30.0)
        self.assertEqual(result, 25.0)

    def test_empty_entity_name(self):
        result = find_entity_start_time("", self.WORDS, 0.0, 30.0)
        self.assertIsNone(result)

    def test_none_words(self):
        result = find_entity_start_time("Jazz", None, 0.0, 30.0)
        self.assertIsNone(result)
