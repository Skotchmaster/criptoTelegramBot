from functools import lru_cache

def make_lru(size: int):
    def decorator(fn):
        return lru_cache(maxsize=size)(fn)
    return decorator
