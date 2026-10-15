import pytest
from fastapi import HTTPException
from app.core.security import check_login_rate_limit, record_failed_login, clear_login_rate_limit
from unittest.mock import patch
import fakeredis


@patch("app.core.security.get_redis_client")
def test_login_rate_limit_blocking(mock_get_redis):
    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    mock_get_redis.return_value = fake_redis

    ip = "192.168.1.10"
    email = "test@clinica.com"

    # First 3 attempts should pass (no exception)
    for _ in range(3):
        check_login_rate_limit(ip, email)
        record_failed_login(ip, email)

    # 4th attempt should raise HTTPException 429 Too Many Requests
    with pytest.raises(HTTPException) as exc_info:
        check_login_rate_limit(ip, email)
    assert exc_info.value.status_code == 429

    # Clear rate limit and verify it passes again
    clear_login_rate_limit(ip, email)
    check_login_rate_limit(ip, email)
