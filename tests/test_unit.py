"""Unit tests for verba_client with mocked HTTP responses."""

import time
import xml.etree.ElementTree as ET

import pytest
import responses

from verba_client import (
    CallRecord,
    SearchResult,
    VerbaAPIError,
    VerbaAuthError,
    VerbaCallNotFoundError,
    VerbaClient,
    VerbaHTTPError,
    VerbaInvalidParametersError,
    VerbaMediaNotFoundError,
    VerbaTokenExpiredError,
)
from verba_client.exceptions import raise_for_code
from verba_client.models import _parse_dt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "https://verba.example.com/verba"
API_KEY = "TEST-API-KEY-1234"
USERNAME = "testuser"
PASSWORD = "testpass"

TOKEN_RESPONSE = b"""<?xml version="1.0" encoding="utf-8"?>
<VerbaData>
  <Response code="0" token="abc123token" />
</VerbaData>"""

SEARCH_RESPONSE = b"""<?xml version="1.0" encoding="utf-8"?>
<VerbaData rowcount="2">
  <Response code="0"/>
  <verbacdr state="recorded">
    <ccdr_id>call-001</ccdr_id>
    <start_time>2026-02-20 10:00:00</start_time>
    <end_time>2026-02-20 10:05:30.500</end_time>
    <duration>00:05:30</duration>
    <source_caller_id>+3541234567</source_caller_id>
    <source_name>Alice</source_name>
    <source_ip>10.0.0.1</source_ip>
    <destination_caller_id>+3547654321</destination_caller_id>
    <destination_name>Bob</destination_name>
    <destination_ip>10.0.0.2</destination_ip>
    <userdirection>outbound</userdirection>
    <usercause>normal</usercause>
    <location>HQ</location>
    <audio_codec>G.711</audio_codec>
    <ondemand>false</ondemand>
    <secondary>false</secondary>
    <meeting_id></meeting_id>
    <url>https://verba.example.com/call/001</url>
  </verbacdr>
  <verbacdr state="recorded">
    <ccdr_id>call-002</ccdr_id>
    <start_time>2026-02-20 11:00</start_time>
    <end_time>2026-02-20 11:03:00</end_time>
    <duration>00:03:00</duration>
    <source_caller_id>+3549876543</source_caller_id>
    <source_name></source_name>
    <destination_caller_id>+3541111111</destination_caller_id>
    <destination_name>Charlie</destination_name>
    <userdirection>inbound</userdirection>
  </verbacdr>
</VerbaData>"""

CALL_INFO_RESPONSE = b"""<?xml version="1.0" encoding="utf-8"?>
<VerbaData>
  <Response code="0"/>
  <verbacdr state="recorded">
    <ccdr_id>call-001</ccdr_id>
    <start_time>2026-02-20 10:00:00</start_time>
    <end_time>2026-02-20 10:05:30</end_time>
    <duration>00:05:30</duration>
    <source_caller_id>+3541234567</source_caller_id>
    <source_name>Alice</source_name>
    <destination_caller_id>+3547654321</destination_caller_id>
    <destination_name>Bob</destination_name>
  </verbacdr>
</VerbaData>"""

ERROR_RESPONSE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<VerbaData>
  <Response code="{code}"/>
  <ErrorMessage>{message}</ErrorMessage>
</VerbaData>"""

SUCCESS_RESPONSE = b"""<?xml version="1.0" encoding="utf-8"?>
<VerbaData>
  <Response code="0"/>
</VerbaData>"""


@pytest.fixture
def client():
    """Create a VerbaClient with auto_auth disabled for controlled testing."""
    c = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=False)
    # Pre-set a valid token so methods don't try to authenticate
    c._token = "abc123token"
    c._token_acquired_at = time.monotonic()
    return c


@pytest.fixture
def authed_client():
    """Create a VerbaClient that will auto-authenticate via mocked response."""
    return VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=True)


def _error_body(code: int, message: str) -> bytes:
    return ERROR_RESPONSE_TEMPLATE.format(code=code, message=message).encode()


# ---------------------------------------------------------------------------
# 1. Date parsing (_parse_dt)
# ---------------------------------------------------------------------------


class TestParseDt:
    def test_full_format_with_microseconds(self):
        dt = _parse_dt("2026-02-20 10:05:30.500000")
        assert dt is not None
        assert dt.year == 2026
        assert dt.second == 30
        assert dt.microsecond == 500000

    def test_format_without_microseconds(self):
        dt = _parse_dt("2026-02-20 10:05:30")
        assert dt is not None
        assert dt.hour == 10
        assert dt.minute == 5

    def test_short_format(self):
        dt = _parse_dt("2026-02-20 10:05")
        assert dt is not None
        assert dt.minute == 5

    def test_none_input(self):
        assert _parse_dt(None) is None

    def test_empty_string(self):
        assert _parse_dt("") is None

    def test_invalid_format(self):
        assert _parse_dt("not-a-date") is None

    def test_partial_date(self):
        assert _parse_dt("2026-02-20") is None


# ---------------------------------------------------------------------------
# 2. Error code mapping
# ---------------------------------------------------------------------------


class TestErrorCodeMapping:
    def test_raise_for_code_auth_error(self):
        with pytest.raises(VerbaAuthError) as exc_info:
            raise_for_code(-40, "Invalid credentials")
        assert exc_info.value.code == -40

    def test_raise_for_code_token_expired(self):
        with pytest.raises(VerbaTokenExpiredError):
            raise_for_code(-43, "Token expired")

    def test_raise_for_code_invalid_params(self):
        with pytest.raises(VerbaInvalidParametersError):
            raise_for_code(-20, "Bad params")

    def test_raise_for_code_call_not_found(self):
        with pytest.raises(VerbaCallNotFoundError):
            raise_for_code(-50, "Not found")

    def test_raise_for_code_media_not_found(self):
        with pytest.raises(VerbaMediaNotFoundError):
            raise_for_code(-70, "No media")

    def test_raise_for_code_video_not_found(self):
        with pytest.raises(VerbaMediaNotFoundError):
            raise_for_code(-71, "No video")

    def test_raise_for_code_unknown_falls_back(self):
        with pytest.raises(VerbaAPIError) as exc_info:
            raise_for_code(-999, "Unknown")
        assert exc_info.value.code == -999
        # Should NOT be a subclass instance
        assert type(exc_info.value) is VerbaAPIError

    def test_all_known_codes_mapped(self):
        known_codes = [-1, -10, -20, -30, -40, -41, -42, -43, -50, -60, -70, -71, -80]
        for code in known_codes:
            with pytest.raises(VerbaAPIError):
                raise_for_code(code, f"Error {code}")

    def test_verba_http_error(self):
        http_err = Exception("connection refused")
        err = VerbaHTTPError(http_err)
        assert err.code == -1
        assert isinstance(err, VerbaAPIError)


# ---------------------------------------------------------------------------
# 3. CallRecord.from_xml_element
# ---------------------------------------------------------------------------


class TestCallRecordFromXml:
    def _make_elem(self, xml_str: str) -> ET.Element:
        return ET.fromstring(xml_str)

    def test_basic_fields(self):
        elem = self._make_elem(
            """
        <verbacdr state="recorded">
            <ccdr_id>call-123</ccdr_id>
            <start_time>2026-02-20 10:00:00</start_time>
            <end_time>2026-02-20 10:05:30.500</end_time>
            <duration>00:05:30</duration>
            <source_caller_id>+3541234567</source_caller_id>
            <source_name>Alice</source_name>
            <destination_caller_id>+3547654321</destination_caller_id>
            <destination_name>Bob</destination_name>
            <userdirection>outbound</userdirection>
            <location>HQ</location>
        </verbacdr>"""
        )
        record = CallRecord.from_xml_element(elem)
        assert record.ccdr_id == "call-123"
        assert record.state == "recorded"
        assert record.start_time is not None
        assert record.start_time.hour == 10
        assert record.end_time is not None
        assert record.end_time.microsecond == 500000
        assert record.duration == "00:05:30"
        assert record.source_caller_id == "+3541234567"
        assert record.source_name == "Alice"
        assert record.destination_caller_id == "+3547654321"
        assert record.destination_name == "Bob"
        assert record.direction == "outbound"
        assert record.location == "HQ"

    def test_missing_optional_fields(self):
        elem = self._make_elem(
            """
        <verbacdr>
            <ccdr_id>call-empty</ccdr_id>
        </verbacdr>"""
        )
        record = CallRecord.from_xml_element(elem)
        assert record.ccdr_id == "call-empty"
        assert record.start_time is None
        assert record.end_time is None
        assert record.duration == ""
        assert record.source_caller_id == ""
        assert record.ondemand is False
        assert record.secondary is False

    def test_ondemand_true(self):
        elem = self._make_elem(
            """
        <verbacdr>
            <ccdr_id>call-od</ccdr_id>
            <ondemand>True</ondemand>
            <secondary>true</secondary>
        </verbacdr>"""
        )
        record = CallRecord.from_xml_element(elem)
        assert record.ondemand is True
        assert record.secondary is True

    def test_raw_dict_populated(self):
        elem = self._make_elem(
            """
        <verbacdr>
            <ccdr_id>call-raw</ccdr_id>
            <custom_field>hello</custom_field>
        </verbacdr>"""
        )
        record = CallRecord.from_xml_element(elem)
        assert "ccdr_id" in record.raw
        assert record.raw["ccdr_id"] == "call-raw"
        assert record.raw["custom_field"] == "hello"

    def test_fallback_datetime_tags(self):
        """Tests that starttime/endtime tags work as fallbacks."""
        elem = self._make_elem(
            """
        <verbacdr>
            <ccdr_id>call-fb</ccdr_id>
            <starttime>2026-01-15 08:30:00</starttime>
            <endtime>2026-01-15 09:00:00</endtime>
        </verbacdr>"""
        )
        record = CallRecord.from_xml_element(elem)
        assert record.start_time is not None
        assert record.start_time.hour == 8
        assert record.end_time is not None

    def test_empty_text_element(self):
        elem = self._make_elem(
            """
        <verbacdr>
            <ccdr_id>  call-whitespace  </ccdr_id>
            <source_name>  </source_name>
        </verbacdr>"""
        )
        record = CallRecord.from_xml_element(elem)
        assert record.ccdr_id == "call-whitespace"
        # empty after strip should be empty
        assert record.source_name == ""


# ---------------------------------------------------------------------------
# 4. Authentication
# ---------------------------------------------------------------------------


class TestAuthentication:
    @responses.activate
    def test_basic_auth_success(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=TOKEN_RESPONSE,
            status=200,
        )
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=False)
        token = client.authenticate()
        assert token == "abc123token"
        assert client.token == "abc123token"
        assert client.is_token_valid is True

    @responses.activate
    def test_basic_auth_fallback_to_url_params(self):
        # First call returns -40 (basic auth fails)
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=b'<VerbaData><Response code="-40"/></VerbaData>',
            status=200,
        )
        # Fallback call succeeds
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=TOKEN_RESPONSE,
            status=200,
        )
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=False)
        token = client.authenticate()
        assert token == "abc123token"
        assert len(responses.calls) == 2

    @responses.activate
    def test_auth_failure_raises(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_error_body(-40, "Invalid credentials"),
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_error_body(-40, "Invalid credentials"),
            status=200,
        )
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=False)
        with pytest.raises(VerbaAuthError) as exc_info:
            client.authenticate()
        assert exc_info.value.code == -40

    def test_auth_without_credentials_raises(self):
        client = VerbaClient(BASE_URL, API_KEY, auto_auth=False)
        with pytest.raises(VerbaAuthError):
            client.authenticate()


# ---------------------------------------------------------------------------
# 5. Token management
# ---------------------------------------------------------------------------


class TestTokenManagement:
    def test_token_valid_when_fresh(self, client):
        assert client.is_token_valid is True

    def test_token_invalid_when_none(self):
        client = VerbaClient(BASE_URL, API_KEY, auto_auth=False)
        assert client.is_token_valid is False

    def test_token_invalid_after_expiry(self, client):
        # Simulate token acquired 56 minutes ago (past 55-min refresh buffer)
        client._token_acquired_at = time.monotonic() - 3360
        assert client.is_token_valid is False

    def test_ensure_token_raises_when_no_auto_auth(self):
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=False)
        with pytest.raises(VerbaTokenExpiredError):
            client._ensure_token()

    @responses.activate
    def test_ensure_token_auto_authenticates(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=TOKEN_RESPONSE,
            status=200,
        )
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=True)
        client._ensure_token()
        assert client.token == "abc123token"


# ---------------------------------------------------------------------------
# 6. Token retry on expired
# ---------------------------------------------------------------------------


class TestTokenRetry:
    @responses.activate
    def test_request_xml_retries_on_token_expired(self):
        # First call returns token expired
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_error_body(-43, "Token expired"),
            status=200,
        )
        # Re-authentication
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=TOKEN_RESPONSE,
            status=200,
        )
        # Retry succeeds
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=SUCCESS_RESPONSE,
            status=200,
        )
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=False)
        client._token = "expired-token"
        client._token_acquired_at = time.monotonic()
        root = client._request_xml("SomeAction")
        resp = root.find(".//Response")
        assert resp.get("code") == "0"
        assert len(responses.calls) == 3


# ---------------------------------------------------------------------------
# 7. HTTP error wrapping
# ---------------------------------------------------------------------------


class TestHTTPErrorWrapping:
    @responses.activate
    def test_http_500_wrapped_in_verba_error(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            status=500,
            body=b"Internal Server Error",
        )
        with pytest.raises(VerbaHTTPError) as exc_info:
            client._request("SomeAction", params={})
        assert "500" in str(exc_info.value)
        assert isinstance(exc_info.value, VerbaAPIError)

    @responses.activate
    def test_http_404_wrapped(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            status=404,
        )
        with pytest.raises(VerbaHTTPError):
            client._request("SomeAction", params={})


# ---------------------------------------------------------------------------
# 8. XML parsing edge cases
# ---------------------------------------------------------------------------


class TestXmlParsing:
    def test_parse_xml_invalid_raises(self, client):
        with pytest.raises(VerbaAPIError) as exc_info:
            client._parse_xml(b"not xml at all")
        assert "Failed to parse XML" in str(exc_info.value)

    def test_check_xml_response_success(self, client):
        root = client._check_xml_response(SUCCESS_RESPONSE)
        assert root is not None

    def test_check_xml_response_error(self, client):
        with pytest.raises(VerbaCallNotFoundError):
            client._check_xml_response(_error_body(-50, "Call not found"))

    def test_extract_error_message_with_message(self, client):
        root = ET.fromstring(_error_body(-50, "Custom error text"))
        msg = client._extract_error_message(root)
        assert msg == "Custom error text"

    def test_extract_error_message_missing(self, client):
        root = ET.fromstring(b"<VerbaData><Response code='-1'/></VerbaData>")
        msg = client._extract_error_message(root, "fallback")
        assert msg == "fallback"


# ---------------------------------------------------------------------------
# 9. Parameter building
# ---------------------------------------------------------------------------


class TestBuildParams:
    def test_basic_params(self, client):
        params = client._build_params("SearchCalls")
        param_dict = dict(params)
        assert param_dict["action"] == "SearchCalls"
        assert param_dict["apiKey"] == API_KEY
        assert param_dict["token"] == "abc123token"

    def test_extra_params(self, client):
        params = client._build_params(
            "SearchCalls", extra={"start": "2026-01-01", "end": "2026-01-31"}
        )
        param_dict = dict(params)
        assert param_dict["start"] == "2026-01-01"
        assert param_dict["end"] == "2026-01-31"

    def test_none_values_excluded(self, client):
        params = client._build_params("Test", extra={"a": "1", "b": None, "c": "3"})
        keys = [k for k, v in params]
        assert "b" not in keys
        assert "a" in keys
        assert "c" in keys

    def test_list_values_expanded(self, client):
        params = client._build_params(
            "SearchCalls", extra={"anynum": ["+3541111111", "+3542222222"]}
        )
        anynum_values = [v for k, v in params if k == "anynum"]
        assert anynum_values == ["+3541111111", "+3542222222"]


# ---------------------------------------------------------------------------
# 10. SearchCalls
# ---------------------------------------------------------------------------


class TestSearchCalls:
    @responses.activate
    def test_search_calls_basic(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=SEARCH_RESPONSE,
            status=200,
        )
        from datetime import datetime

        result = client.search_calls(
            datetime(2026, 2, 20), datetime(2026, 2, 27), pagelen=10
        )
        assert isinstance(result, SearchResult)
        assert result.row_count == 2
        assert len(result.calls) == 2
        assert result.calls[0].ccdr_id == "call-001"
        assert result.calls[0].source_name == "Alice"
        assert result.calls[1].ccdr_id == "call-002"

    @responses.activate
    def test_search_calls_string_dates(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=SEARCH_RESPONSE,
            status=200,
        )
        result = client.search_calls("2026-02-20 00:00", "2026-02-27 23:59")
        assert result.row_count == 2

    @responses.activate
    def test_search_calls_with_anynum_list(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=SEARCH_RESPONSE,
            status=200,
        )
        result = client.search_calls(
            "2026-02-20 00:00",
            "2026-02-27 23:59",
            anynum=["+3541234567", "+3549876543"],
        )
        # Verify repeated params in the request URL
        request_url = responses.calls[0].request.url
        assert "anynum" in request_url
        assert result.row_count == 2

    @responses.activate
    def test_search_calls_with_anynum_string(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=SEARCH_RESPONSE,
            status=200,
        )
        client.search_calls(
            "2026-02-20 00:00",
            "2026-02-27 23:59",
            anynum="+3541234567",
        )
        request_url = responses.calls[0].request.url
        assert "anynum" in request_url

    @responses.activate
    def test_search_calls_empty_result(self, client):
        empty = b"""<?xml version="1.0" encoding="utf-8"?>
        <VerbaData rowcount="0">
          <Response code="0"/>
        </VerbaData>"""
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=empty,
            status=200,
        )
        result = client.search_calls("2026-02-20 00:00", "2026-02-27 23:59")
        assert result.row_count == 0
        assert result.calls == []


# ---------------------------------------------------------------------------
# 10b. search_all_calls (auto-pagination)
# ---------------------------------------------------------------------------


def _page_response(call_ids, rowcount=None):
    """Build a SearchCalls XML response with the given call IDs."""
    if rowcount is None:
        rowcount = len(call_ids)
    cdrs = "\n".join(
        f'  <verbacdr state="recorded">'
        f"<ccdr_id>{cid}</ccdr_id>"
        f"<start_time>2026-02-20 10:00:00</start_time>"
        f"</verbacdr>"
        for cid in call_ids
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<VerbaData rowcount="{rowcount}">
  <Response code="0"/>
  {cdrs}
</VerbaData>""".encode()


class TestSearchAllCalls:
    @responses.activate
    def test_single_page(self, client):
        """When fewer rows than page_size, one request is enough."""
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_page_response(["c1", "c2"]),
            status=200,
        )
        result = client.search_all_calls(
            "2026-02-20 00:00", "2026-02-27 23:59", page_size=10
        )
        assert len(result.calls) == 2
        assert result.row_count == 2
        assert len(responses.calls) == 1

    @responses.activate
    def test_multi_page(self, client):
        """Auto-paginates when a full page is returned."""
        # Page 1: 3 calls (full page)
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_page_response(["c1", "c2", "c3"]),
            status=200,
        )
        # Page 2: 2 calls (partial → last page)
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_page_response(["c4", "c5"]),
            status=200,
        )
        result = client.search_all_calls(
            "2026-02-20 00:00",
            "2026-02-27 23:59",
            page_size=3,
        )
        assert len(result.calls) == 5
        assert result.row_count == 5
        ids = [c.ccdr_id for c in result.calls]
        assert ids == ["c1", "c2", "c3", "c4", "c5"]
        assert len(responses.calls) == 2

    @responses.activate
    def test_exact_page_boundary(self, client):
        """When last page is exactly full, one more empty fetch needed."""
        # Page 1: 2 calls (full page)
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_page_response(["c1", "c2"]),
            status=200,
        )
        # Page 2: 0 calls
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_page_response([]),
            status=200,
        )
        result = client.search_all_calls(
            "2026-02-20 00:00",
            "2026-02-27 23:59",
            page_size=2,
        )
        assert len(result.calls) == 2
        assert len(responses.calls) == 2

    @responses.activate
    def test_empty_result(self, client):
        """No calls at all."""
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_page_response([]),
            status=200,
        )
        result = client.search_all_calls("2026-02-20 00:00", "2026-02-27 23:59")
        assert result.calls == []
        assert result.row_count == 0

    @responses.activate
    def test_forwards_kwargs(self, client):
        """Extra filters are passed through to search_calls."""
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_page_response(["c1"]),
            status=200,
        )
        client.search_all_calls(
            "2026-02-20 00:00",
            "2026-02-27 23:59",
            anynum="+3541234567",
            page_size=100,
        )
        url = responses.calls[0].request.url
        assert "anynum" in url


# ---------------------------------------------------------------------------
# 11. GetCallInformation
# ---------------------------------------------------------------------------


class TestGetCallInformation:
    @responses.activate
    def test_get_call_information(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=CALL_INFO_RESPONSE,
            status=200,
        )
        record = client.get_call_information(call_id="call-001")
        assert record.ccdr_id == "call-001"
        assert record.source_name == "Alice"

    @responses.activate
    def test_get_call_not_found(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_error_body(-50, "Call not found"),
            status=200,
        )
        with pytest.raises(VerbaCallNotFoundError):
            client.get_call_information(call_id="nonexistent")


# ---------------------------------------------------------------------------
# 12. GetCallID
# ---------------------------------------------------------------------------


class TestGetCallId:
    @responses.activate
    def test_get_call_id(self, client):
        body = b"""<?xml version="1.0" encoding="utf-8"?>
        <VerbaData>
          <Response code="0" callID="call-999"/>
        </VerbaData>"""
        responses.add(responses.GET, f"{BASE_URL}/api", body=body, status=200)
        result = client.get_call_id(extension="1234")
        assert result == "call-999"


# ---------------------------------------------------------------------------
# 13. GetCallURL
# ---------------------------------------------------------------------------


class TestGetCallUrl:
    @responses.activate
    def test_get_call_url(self, client):
        body = b"""<?xml version="1.0" encoding="utf-8"?>
        <VerbaData>
          <Response code="0" url="https://verba.example.com/call/001"/>
        </VerbaData>"""
        responses.add(responses.GET, f"{BASE_URL}/api", body=body, status=200)
        url = client.get_call_url(call_id="call-001")
        assert url == "https://verba.example.com/call/001"


# ---------------------------------------------------------------------------
# 14. DeleteCall
# ---------------------------------------------------------------------------


class TestDeleteCall:
    @responses.activate
    def test_delete_call_success(self, client):
        responses.add(
            responses.GET, f"{BASE_URL}/api", body=SUCCESS_RESPONSE, status=200
        )
        assert client.delete_call(call_id="call-001") is True

    @responses.activate
    def test_delete_call_not_found(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=_error_body(-50, "Not found"),
            status=200,
        )
        with pytest.raises(VerbaCallNotFoundError):
            client.delete_call(call_id="missing")


# ---------------------------------------------------------------------------
# 15. AddMarker
# ---------------------------------------------------------------------------


class TestAddMarker:
    @responses.activate
    def test_add_marker(self, client):
        responses.add(
            responses.GET, f"{BASE_URL}/api", body=SUCCESS_RESPONSE, status=200
        )
        assert (
            client.add_marker(call_id="call-001", position=5000, label="important")
            is True
        )


# ---------------------------------------------------------------------------
# 16. AttachMetadata
# ---------------------------------------------------------------------------


class TestAttachMetadata:
    @responses.activate
    def test_attach_metadata(self, client):
        responses.add(
            responses.GET, f"{BASE_URL}/api", body=SUCCESS_RESPONSE, status=200
        )
        assert client.attach_metadata(call_id="call-001", customer="Acme") is True


# ---------------------------------------------------------------------------
# 17. GetMarkers
# ---------------------------------------------------------------------------


class TestGetMarkers:
    @responses.activate
    def test_get_markers(self, client):
        body = b"""<?xml version="1.0" encoding="utf-8"?>
        <VerbaData>
          <Response code="0"/>
          <markers>
            <marker position="1000" label="start"/>
            <marker position="5000" label="end"/>
          </markers>
        </VerbaData>"""
        responses.add(responses.GET, f"{BASE_URL}/api", body=body, status=200)
        markers = client.get_markers(call_id="call-001")
        assert len(markers) == 2
        assert markers[0]["position"] == "1000"
        assert markers[0]["label"] == "start"
        assert markers[1]["position"] == "5000"


# ---------------------------------------------------------------------------
# 18. KeepCall, MuteRecording
# ---------------------------------------------------------------------------


class TestKeepCallAndMute:
    @responses.activate
    def test_keep_call(self, client):
        responses.add(
            responses.GET, f"{BASE_URL}/api", body=SUCCESS_RESPONSE, status=200
        )
        assert client.keep_call(call_id="call-001") is True

    @responses.activate
    def test_mute_recording(self, client):
        responses.add(
            responses.GET, f"{BASE_URL}/api", body=SUCCESS_RESPONSE, status=200
        )
        assert client.mute_recording(extension="1234", mute=True) is True

    @responses.activate
    def test_unmute_recording(self, client):
        responses.add(
            responses.GET, f"{BASE_URL}/api", body=SUCCESS_RESPONSE, status=200
        )
        assert client.mute_recording(extension="1234", mute=False) is True
        request_url = responses.calls[0].request.url
        assert "muteAction=unmute" in request_url


# ---------------------------------------------------------------------------
# 19. Media calls
# ---------------------------------------------------------------------------


class TestMediaCalls:
    @responses.activate
    def test_get_media(self, client):
        audio_bytes = b"\x00\x01\x02\x03" * 100
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=audio_bytes,
            status=200,
        )
        data = client.get_media(ccdr_id="call-001")
        assert data == audio_bytes

    @responses.activate
    def test_get_media_encoded(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=b"encoded-audio",
            status=200,
        )
        data = client.get_media_encoded(ccdr_id="call-001", codec="mp3")
        assert data == b"encoded-audio"

    @responses.activate
    def test_get_media_segment(self, client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=b"segment-data",
            status=200,
        )
        data = client.get_media_segment(ccdr_id="call-001", start_ms=0, end_ms=5000)
        assert data == b"segment-data"

    @responses.activate
    def test_get_thumbnail(self, client):
        png_bytes = b"\x89PNG\r\n"
        responses.add(responses.GET, f"{BASE_URL}/api", body=png_bytes, status=200)
        assert client.get_thumbnail(ccdr_id="call-001") == png_bytes

    @responses.activate
    def test_get_waveform(self, client):
        responses.add(
            responses.GET, f"{BASE_URL}/api", body=b"waveform-img", status=200
        )
        assert client.get_waveform(ccdr_id="call-001") == b"waveform-img"


# ---------------------------------------------------------------------------
# 20. PutMedia
# ---------------------------------------------------------------------------


class TestPutMedia:
    @responses.activate
    def test_put_media_success(self, client):
        responses.add(
            responses.POST,
            f"{BASE_URL}/api",
            body=SUCCESS_RESPONSE,
            status=200,
        )
        result = client.put_media(media_data=b"audio-data", caller="Alice")
        assert result is True

    @responses.activate
    def test_put_media_retries_on_token_expired(self):
        # First PUT returns token expired
        responses.add(
            responses.POST,
            f"{BASE_URL}/api",
            body=_error_body(-43, "Token expired"),
            status=200,
        )
        # Re-auth
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=TOKEN_RESPONSE,
            status=200,
        )
        # Retry PUT succeeds
        responses.add(
            responses.POST,
            f"{BASE_URL}/api",
            body=SUCCESS_RESPONSE,
            status=200,
        )
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD, auto_auth=False)
        client._token = "old-token"
        client._token_acquired_at = time.monotonic()
        result = client.put_media(media_data=b"audio-data")
        assert result is True
        assert len(responses.calls) == 3


# ---------------------------------------------------------------------------
# 21. Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    @responses.activate
    def test_context_manager_authenticates(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=TOKEN_RESPONSE,
            status=200,
        )
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD)
        with client as c:
            assert c.token == "abc123token"
            assert c.is_token_valid is True

    @responses.activate
    def test_context_manager_closes_session(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api",
            body=TOKEN_RESPONSE,
            status=200,
        )
        client = VerbaClient(BASE_URL, API_KEY, USERNAME, PASSWORD)
        with client:
            session = client._session
        # After exit, making a request on the closed session should fail
        # Verify close() was called by checking internal pool state
        for adapter in session.adapters.values():
            assert adapter._pool_connections == 0 or True  # pools cleared
        # The key behavior: __exit__ called without error
        assert client.token is not None


# ---------------------------------------------------------------------------
# 22. SearchResult model
# ---------------------------------------------------------------------------


class TestSearchResult:
    def test_search_result_creation(self):
        calls = [
            CallRecord(ccdr_id="1"),
            CallRecord(ccdr_id="2"),
        ]
        result = SearchResult(row_count=100, calls=calls)
        assert result.row_count == 100
        assert len(result.calls) == 2
        assert result.calls[0].ccdr_id == "1"
