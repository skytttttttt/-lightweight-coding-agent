def score(player_hits, boss_hits):
    # BUG: boss 命中扣分权重应为 3
    return (player_hits * 2) - (boss_hits * 1)
