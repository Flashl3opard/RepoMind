from app.github_app.rate_limit import InstallationRateLimiter, TokenBucket


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def test_token_bucket_allows_up_to_capacity():
    clock = FakeClock()
    bucket = TokenBucket(capacity=3, refill_per_second=0, clock=clock)
    assert bucket.try_acquire()
    assert bucket.try_acquire()
    assert bucket.try_acquire()
    assert not bucket.try_acquire()


def test_token_bucket_refills_over_time():
    clock = FakeClock()
    bucket = TokenBucket(capacity=1, refill_per_second=1, clock=clock)
    assert bucket.try_acquire()
    assert not bucket.try_acquire()

    clock.t += 1.0
    assert bucket.try_acquire()


def test_token_bucket_never_exceeds_capacity():
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_per_second=100, clock=clock)
    clock.t += 1000  # huge elapsed time, refill should still cap at capacity
    assert bucket.try_acquire()
    assert bucket.try_acquire()
    assert not bucket.try_acquire()


def test_installation_rate_limiter_tracks_installations_independently():
    clock = FakeClock()
    limiter = InstallationRateLimiter(capacity=1, refill_per_minute=0, clock=clock)
    assert limiter.allow(1)
    assert not limiter.allow(1)
    assert limiter.allow(2)  # separate bucket, unaffected by installation 1


def test_installation_rate_limiter_refill_per_minute_converted_to_per_second():
    clock = FakeClock()
    limiter = InstallationRateLimiter(capacity=1, refill_per_minute=60, clock=clock)
    assert limiter.allow(1)
    assert not limiter.allow(1)
    clock.t += 1.0  # 60/min == 1/sec
    assert limiter.allow(1)
