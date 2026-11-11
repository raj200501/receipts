from throttle.clock import ManualClock
from throttle.limiter import Decision, Limiter
from throttle.policy import Limit, Policy

POLICY = Policy(
    default=Limit(burst=3, per_minute=60),
    clients={"reports-web": Limit(burst=2, per_minute=30)},
)


def test_new_client_gets_its_burst() -> None:
    limiter = Limiter(POLICY, ManualClock())
    assert [limiter.check("mobile-app").allowed for _ in range(4)] == [True, True, True, False]


def test_clients_have_separate_buckets() -> None:
    limiter = Limiter(POLICY, ManualClock())
    for _ in range(3):
        limiter.check("mobile-app")
    assert limiter.check("partner-portal").allowed


def test_client_limit_comes_from_the_policy() -> None:
    limiter = Limiter(POLICY, ManualClock())
    assert [limiter.check("reports-web").allowed for _ in range(3)] == [True, True, False]


def test_bucket_refills_between_requests() -> None:
    clock = ManualClock()
    limiter = Limiter(POLICY, clock)
    allowed = []
    for _ in range(8):
        allowed.append(limiter.check("mobile-app").allowed)
        clock.advance(0.5)
    assert allowed == [True, True, True, True, True, False, True, False]


def test_allowed_request_has_no_retry_after() -> None:
    assert Limiter(POLICY, ManualClock()).check("mobile-app") == Decision(True, 0)


def test_rejected_request_has_a_retry_after() -> None:
    limiter = Limiter(POLICY, ManualClock())
    limiter.check("reports-web")
    limiter.check("reports-web")
    assert limiter.check("reports-web") == Decision(False, 2)


def test_idle_clients_are_forgotten() -> None:
    clock = ManualClock()
    limiter = Limiter(POLICY, clock)
    limiter.check("mobile-app")
    clock.advance(61)
    limiter.check("partner-portal")
    assert limiter.tracked_clients() == ["partner-portal"]


def test_recent_clients_are_kept() -> None:
    clock = ManualClock()
    limiter = Limiter(POLICY, clock)
    limiter.check("mobile-app")
    clock.advance(30)
    limiter.check("partner-portal")
    assert limiter.tracked_clients() == ["mobile-app", "partner-portal"]
