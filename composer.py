"""Select a current time topic; no built-in character or dialogue templates."""
import random
def pick(topics, state, rng=None):
    return (rng or random).choice(topics) if topics else None
