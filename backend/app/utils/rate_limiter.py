from app.core.redis import redis_client
from app.errors.http_error import HTTPError

from redis.asyncio import Redis
import tiktoken

from time import time
from uuid import UUID
from typing import Any
import asyncio

TOKEN_BUCKET_LUA = """
local bucket = redis.call('hmget', KEYS[1], 'tokens', 'last_updated')
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local tokens = capacity
local last_updated = now

if bucket[1] and bucket[2] then
    tokens = tonumber(bucket[1])
    last_updated = tonumber(bucket[2])
    local delta = math.max(0, now - last_updated)
    tokens = math.min(capacity, tokens + delta * refill_rate)
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call('hmset', KEYS[1], 'tokens', tokens, 'last_updated', now)
    redis.call('expire', KEYS[1], 86400) -- TTL 1 day
    return 1 -- Allowed
else
    redis.call('hmset', KEYS[1], 'tokens', tokens, 'last_updated', now)
    return 0 -- Denied
end
"""


class TokenBucketRateLimiting:
    def __init__(self, redis_client: Redis, tokenizer: dict[str, tiktoken.Encoding]):
        self.redis_client = redis_client

        self.ANON_MAX_CAP = 40_000
        self.SIGN_MAX_CAP = 100_000

        self.ANON_REFILL_RATE = 0.463
        self.SIGN_REFILL_RATE = 1.157
        self.enc = tokenizer.get("cl100k_base", None)

    async def validate_request(
        self, user_id: UUID, is_annoymous: bool, cost: float
    ) -> Any:

        capacity = self.ANON_MAX_CAP if is_annoymous else self.SIGN_MAX_CAP
        refill_rate = self.ANON_REFILL_RATE if is_annoymous else self.SIGN_REFILL_RATE

        # ip = request.headers.get("x-verified-client-ip", None)
        identifier = f"{is_annoymous}:{str(user_id)}"

        bucket_key = f"rate_limit:{identifier}"

        now = time.time()

        # async with redis_client.pipeline(transaction=True) as pipe:
        #     while True:
        #         try:
        #             await pipe.watch(bucket_key)

        #             data = await pipe.hmget(bucket_key, "tokens", "last_updated")

        #             tokens = self.capacity
        #             last_updated = now

        #             if data[0] is not None and data[1] is not None:
        #                 tokens = float(data[0])
        #                 last_updated = float(data[1])

        #                 delta = max(0, now - last_updated)
        #                 tokens = min(self.capacity, tokens + delta * self.refill_rate)

        #             if tokens >= self.cost:
        #                 tokens -= self.cost
        #                 allowed = True
        #             else:
        #                 allowed = False

        #             pipe.multi()
        #             pipe.hset(bucket_key, mapping={"tokens": tokens, "last_updated": now})
        #             pipe.expire(bucket_key, 86400)

        #             await pipe.execute()

        #             if not allowed:
        #                 raise HTTPException(
        #                     status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        #                     detail="Rate limit exceeded."
        #                 )

        #             break

        #         except WatchError as e:
        #             continue

        result = await redis_client.eval(
            TOKEN_BUCKET_LUA,
            1,
            bucket_key,
            capacity,
            refill_rate,
            cost,
            now,
        )

        if result == 0:
            detail_msg = (
                "ANONYMOUS RATE LIMIT EXCEEDED. PLEASE SIGN IN FOR HIGHER LIMITS."
                if is_annoymous
                else "RATE LIMIT EXCEEDED. PLEASE TRY AGAIN LATER."
            )

            raise HTTPError(
                status=429,
                message=detail_msg,
            )

    async def count_token(
        self, user_prompt: str, history: list[str], retrived_content: str
    ) -> float:
        if self.enc is None:
            raise HTTPError(status=500, message="INTERNAL SERVER ERROR")

        all_text = [user_prompt, *history, retrived_content]

        non_empty_text = [t for t in all_text if t]

        if not non_empty_text:
            return 0

        token_lists = await asyncio.to_thread(self.enc.encode_batch, non_empty_text)

        return sum(len(tokens) for tokens in token_lists)
