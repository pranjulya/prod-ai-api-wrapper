from redis import asyncio as redis


def create_redis(url: str):
    return redis.from_url(url, decode_responses=True)
