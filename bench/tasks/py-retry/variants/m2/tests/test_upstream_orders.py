import pytest
from retrykit.partner import BASE_URL, build_request, order_status, token


def test_request_targets_the_order() -> None:
    request = build_request("A-17", "t0ken")
    assert request.full_url == f"{BASE_URL}/orders/A-17"


def test_request_carries_the_bearer_token() -> None:
    request = build_request("A-17", "t0ken")
    assert request.get_header("Authorization") == "Bearer t0ken"


def test_token_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTNER_API_TOKEN", "from-env")
    assert token() == "from-env"


def test_missing_token_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARTNER_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="PARTNER_API_TOKEN"):
        token()


def test_order_status_from_the_partner_api() -> None:
    # Needs PARTNER_API_TOKEN, a secret that only the CI runner has.
    assert order_status("A-17") in {"open", "shipped", "closed"}
