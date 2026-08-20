import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from word_counter import count_words, count_words_by_length

def test_count_words_unchanged():
    assert count_words('a a b') == {'a': 2, 'b': 1}

def test_by_length():
    assert count_words_by_length('cat dog cat bird', 3) == {'cat': 2, 'dog': 1}

def test_by_length_empty():
    assert count_words_by_length('', 3) == {}

def test_by_length_no_match():
    assert count_words_by_length('a bb ccc', 2) == {'bb': 1}
