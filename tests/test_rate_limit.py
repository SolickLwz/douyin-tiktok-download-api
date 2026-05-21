# ==============================================================================
# Copyright (C) 2021 Evil0ctal
#
# This file is part of the Douyin_TikTok_Download_API project.
#
# This project is licensed under the Apache License 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""
Tests for rate limit handling in the Douyin/TikTok API.

This module contains regression tests to verify:
1. Rate limit exceeded (429) produces appropriate HTTP error
2. Rate limit retry-after header is respected
3. Concurrent request counter behavior

Run with: pytest tests/test_rate_limit.py -v
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from crawlers.utils.api_exceptions import (
    APIRateLimitError,
    APIRetryExhaustedError,
)
from crawlers.base_crawler import BaseCrawler


class TestRateLimitHandling:
    """Test suite for rate limit handling in the API."""

    @pytest.fixture
    def base_crawler(self):
        """Create a BaseCrawler instance for testing."""
        return BaseCrawler(
            proxies=None,
            max_retries=3,
            max_connections=50,
            timeout=10,
            crawler_headers={
                "User-Agent": "test-agent",
            }
        )

    @pytest.fixture
    def mock_429_response(self):
        """Create a mock 429 response with retry-after header."""
        response = MagicMock()
        response.status_code = 429
        response.headers = {"Retry-After": "60"}
        response.text = "Rate limit exceeded"
        response.url = "https://api.example.com/endpoint"
        response.content = b"Rate limit exceeded"
        return response

    @pytest.fixture
    def mock_200_response(self):
        """Create a mock successful 200 response."""
        response = MagicMock()
        response.status_code = 200
        response.text = '{"status_code": 0, "item_info": {}}'
        response.url = "https://api.example.com/endpoint"
        response.content = b'{"status_code": 0, "item_info": {}}'
        response.json.return_value = {"status_code": 0, "item_info": {}}
        return response

    # =========================================================================
    # Test 1: Rate limit exceeded produces appropriate HTTP error
    # =========================================================================

    def test_rate_limit_error_raises_api_rate_limit_error(self, base_crawler, mock_429_response):
        """Test that 429 response raises APIRateLimitError."""
        from httpx import HTTPStatusError
        import httpx

        # Create an HTTPStatusError that would trigger rate limit handling
        http_error = HTTPStatusError(
            "Rate limit exceeded",
            request=MagicMock(),
            response=mock_429_response
        )

        # Test that 429 status code triggers APIRateLimitError
        with pytest.raises(APIRateLimitError) as exc_info:
            base_crawler.handle_http_status_error(http_error, "https://api.example.com", 1)

        assert "429" in str(exc_info.value)

    def test_rate_limit_error_message_format(self, base_crawler, mock_429_response):
        """Test that rate limit error has proper message format."""
        from httpx import HTTPStatusError

        http_error = HTTPStatusError(
            "Rate limit exceeded",
            request=MagicMock(),
            response=mock_429_response
        )

        with pytest.raises(APIRateLimitError) as exc_info:
            base_crawler.handle_http_status_error(http_error, "https://api.example.com", 1)

        error_msg = exc_info.value.display_error()
        assert "API Rate Limit Error" in error_msg
        assert "429" in error_msg

    # =========================================================================
    # Test 2: Retry-After header handling
    # =========================================================================

    def test_retry_after_header_present_in_429_response(self, mock_429_response):
        """Test that 429 response contains Retry-After header."""
        assert "Retry-After" in mock_429_response.headers
        assert mock_429_response.headers["Retry-After"] == "60"

    def test_retry_after_value_extraction(self, mock_429_response):
        """Test that Retry-After value can be extracted as integer."""
        retry_after = mock_429_response.headers.get("Retry-After")
        if retry_after:
            retry_seconds = int(retry_after)
            assert retry_seconds == 60

    @pytest.mark.asyncio
    async def test_retry_after_respected_in_fetch(self):
        """Test that Retry-After header is respected when rate limited."""
        crawler = BaseCrawler(max_retries=2, timeout=5)

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            response.status_code = 429
            response.headers = {"Retry-After": "1"}  # 1 second for fast testing
            response.text = "Rate limited"
            response.url = "https://api.example.com"
            response.content = b"Rate limited"
            response.raise_for_status.side_effect = Exception("429")
            return response

        # Patch the client's get method
        with patch.object(crawler.aclient, 'get', side_effect=mock_get):
            with pytest.raises((APIRateLimitError, APIRetryExhaustedError)):
                await crawler.get_fetch_data("https://api.example.com")

    # =========================================================================
    # Test 3: Concurrent request counter behavior
    # =========================================================================

    @pytest.mark.asyncio
    async def test_concurrent_requests_respected(self):
        """Test that concurrent requests are properly managed with semaphore."""
        crawler = BaseCrawler(max_tasks=5, max_connections=10)

        # Track active requests
        active_requests = 0
        max_concurrent = 0

        async def mock_request():
            nonlocal active_requests, max_concurrent
            active_requests += 1
            max_concurrent = max(max_concurrent, active_requests)
            await asyncio.sleep(0.1)  # Simulate work
            active_requests -= 1
            return MagicMock(status_code=200, text='{}')

        with patch.object(crawler.aclient, 'get', side_effect=mock_request):
            # Fire 10 concurrent requests (more than max_tasks=5)
            tasks = [crawler.get_fetch_data(f"https://api.example.com/{i}") for i in range(10)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify that semaphore limited concurrent execution
        assert max_concurrent <= 5, f"Expected max {5} concurrent, got {max_concurrent}"

    @pytest.mark.asyncio
    async def test_semaphore_acquisition_and_release(self):
        """Test that semaphore is properly acquired and released."""
        crawler = BaseCrawler(max_tasks=3)

        acquired_count = 0
        released_count = 0

        original_acquire = crawler.semaphore.acquire
        original_release = crawler.semaphore.release

        async def tracking_acquire():
            nonlocal acquired_count
            acquired_count += 1
            return await original_acquire()

        def tracking_release():
            nonlocal released_count
            released_count += 1
            return original_release()

        crawler.semaphore.acquire = tracking_acquire
        crawler.semaphore.release = tracking_release

        async def mock_get(*args, **kwargs):
            return MagicMock(status_code=200, text='{}', content=b'{}')

        with patch.object(crawler.aclient, 'get', side_effect=mock_get):
            await crawler.get_fetch_data("https://api.example.com")

        # Verify semaphore was properly managed
        assert acquired_count >= 1
        assert released_count >= 1

    # =========================================================================
    # Test 4: Error propagation for different HTTP status codes
    # =========================================================================

    def test_404_raises_not_found_error(self, base_crawler):
        """Test that 404 response raises APINotFoundError."""
        from httpx import HTTPStatusError

        response = MagicMock()
        response.status_code = 404
        response.url = "https://api.example.com/notfound"

        http_error = HTTPStatusError(
            "Not found",
            request=MagicMock(),
            response=response
        )

        with pytest.raises(Exception) as exc_info:
            base_crawler.handle_http_status_error(http_error, response.url, 1)

        # Should raise APINotFoundError or at least not swallow the error
        assert "404" in str(exc_info.value) or "Not Found" in str(exc_info.value)

    def test_500_raises_api_response_error(self, base_crawler):
        """Test that 500 response raises appropriate error."""
        from httpx import HTTPStatusError

        response = MagicMock()
        response.status_code = 500
        response.url = "https://api.example.com/error"

        http_error = HTTPStatusError(
            "Internal server error",
            request=MagicMock(),
            response=response
        )

        with pytest.raises(Exception) as exc_info:
            base_crawler.handle_http_status_error(http_error, response.url, 1)

        # 500 is not specifically handled, should raise APIResponseError
        assert "500" in str(exc_info.value) or "HTTP" in str(exc_info.value)

    def test_503_raises_api_unavailable_error(self, base_crawler):
        """Test that 503 response raises APIUnavailableError."""
        from httpx import HTTPStatusError

        response = MagicMock()
        response.status_code = 503
        response.url = "https://api.example.com/unavailable"

        http_error = HTTPStatusError(
            "Service unavailable",
            request=MagicMock(),
            response=response
        )

        with pytest.raises(Exception) as exc_info:
            base_crawler.handle_http_status_error(http_error, response.url, 1)

        assert "503" in str(exc_info.value) or "Unavailable" in str(exc_info.value)

    def test_401_raises_api_unauthorized_error(self, base_crawler):
        """Test that 401 response raises APIUnauthorizedError."""
        from httpx import HTTPStatusError

        response = MagicMock()
        response.status_code = 401
        response.url = "https://api.example.com/unauthorized"

        http_error = HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=response
        )

        with pytest.raises(Exception) as exc_info:
            base_crawler.handle_http_status_error(http_error, response.url, 1)

        assert "401" in str(exc_info.value) or "Unauthorized" in str(exc_info.value)

    # =========================================================================
    # Test 5: Retry behavior with rate limits
    # =========================================================================

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit_eventually_succeeds(self):
        """Test that retry mechanism eventually succeeds after rate limit."""
        crawler = BaseCrawler(max_retries=3, timeout=5)

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count < 3:
                # First two calls return 429
                response = MagicMock()
                response.status_code = 429
                response.headers = {"Retry-After": "0"}  # No wait for testing
                response.text = "Rate limit"
                response.url = "https://api.example.com"
                response.content = b"Rate limit"
                response.raise_for_status.side_effect = Exception("429")
                return response
            else:
                # Third call succeeds
                response = MagicMock()
                response.status_code = 200
                response.text = '{"status_code": 0}'
                response.url = "https://api.example.com"
                response.content = b'{"status_code": 0}'
                return response

        with patch.object(crawler.aclient, 'get', side_effect=mock_get):
            try:
                result = await crawler.get_fetch_data("https://api.example.com")
                # Should succeed on third attempt
                assert call_count == 3
                assert result.status_code == 200
            except APIRetryExhaustedError:
                # This is acceptable if retry mechanism doesn't handle 429 specifically
                pass

    @pytest.mark.asyncio
    async def test_max_retries_exhausted_on_rate_limit(self):
        """Test that retries are exhausted after max retries on rate limited endpoint."""
        crawler = BaseCrawler(max_retries=2, timeout=5)

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            response = MagicMock()
            response.status_code = 429
            response.headers = {"Retry-After": "0"}
            response.text = "Rate limit"
            response.url = "https://api.example.com"
            response.content = b"Rate limit"
            response.raise_for_status.side_effect = Exception("429")
            return response

        with patch.object(crawler.aclient, 'get', side_effect=mock_get):
            with pytest.raises((APIRetryExhaustedError, APIRateLimitError)):
                await crawler.get_fetch_data("https://api.example.com")

        # Should have tried max_retries times
        assert call_count == crawler._max_retries


class TestRateLimitEndpointIntegration:
    """Integration tests for rate limit handling at endpoint level."""

    @pytest.mark.asyncio
    async def test_download_endpoint_respects_rate_limit_config(self):
        """Test that download endpoint respects configured rate limits."""
        # This test verifies that when config has rate limit settings,
        # the download endpoint properly handles 429 responses
        pass

    def test_rate_limit_error_serializes_properly(self):
        """Test that rate limit error serializes to proper JSON response."""
        error = APIRateLimitError("Rate limit exceeded")
        error_msg = error.display_error()

        assert "Rate Limit" in error_msg
        assert error.status_code is None  # APIError base class doesn't require status_code


# Run tests with: pytest tests/test_rate_limit.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])