# ratings.py
from collections import defaultdict
import math

def expected_score(rating_a, rating_b):
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def update_ratings(ra, rb, score_a, score_b, k=20):
    total_games = score_a + score_b
    if total_games == 0:
        return ra, rb

    actual_a = score_a / total_games
    actual_b = score_b / total_games

    expected_a = expected_score(ra, rb)
    expected_b = 1 - expected_a

    ra_new = ra + k * (actual_a - expected_a)
    rb_new = rb + k * (actual_b - expected_b)
    return ra_new, rb_new

def get_final_ratings(results_list):
    """
    Takes a list of results like:
    [{"BotA": "A", "BotB": "B", "BotAWins": 52, "BotBWins": 48}, ...]
    and returns a list of tuples: [("A", 1512.3), ("B", 1487.7), ...]
    """
    ratings = defaultdict(lambda: 1500)

    for match in results_list:
        a = match["BotA"]
        b = match["BotB"]
        a_wins = match["BotAWins"]
        b_wins = match["BotBWins"]

        ra, rb = ratings[a], ratings[b]
        ra_new, rb_new = update_ratings(ra, rb, a_wins, b_wins)
        ratings[a], ratings[b] = ra_new, rb_new

    return sorted(ratings.items(), key=lambda x: x[1], reverse=True)
