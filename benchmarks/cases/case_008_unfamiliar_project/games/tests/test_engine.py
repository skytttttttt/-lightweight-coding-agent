from games.arena.engine import score

def test_score_mixed():
    assert score(5, 2) == 10 - 6  # 5*2 - 2*3

def test_score_zero():
    assert score(0, 0) == 0

def test_score_penalty():
    assert score(1, 1) == 2 - 3
