"""Verba HTTP Business API client.

Docs: https://verbalabs.atlassian.net/wiki/spaces/docs/pages/6816935/API+authentication

Supports all HTTP Business API actions:
  - Authentication: RequestToken
  - Metadata: SearchCalls, GetCallInformation, GetCallID, GetCallURL,
              DeleteCall, AddMarker, AttachMetadata, GetMarkers,
              GetVoiceQuality, KeepCall, MuteRecording
  - Media:    GetMedia, GetMediaEncoded, GetMediaLive, GetMediaSegment,
              GetThumbnail, GetWaveform, PutMedia
"""

from __future__ import annotations

import base64
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import requests

from verba_client.exceptions import (
    VerbaAPIError,
    VerbaAuthError,
    VerbaHTTPError,
    VerbaTokenExpiredError,
    raise_for_code,
)
from verba_client.models import CallRecord, SearchResult

logger = logging.getLogger("verba_client")

# Token lifetime is 1 hour per docs; refresh with 5 min buffer
_TOKEN_LIFETIME = 3600
_TOKEN_REFRESH_BUFFER = 300


class VerbaClient:
    """Client for the Verba (VFC Capture) HTTP Business API.

    Args:
        base_url: Base URL of the Verba server (e.g. "http://upptaka.siminn.is/verba").
        api_key: API key GUID issued through the Verba web interface.
        username: Login username for token-based auth.
        password: Login password for token-based auth.
        timeout: HTTP request timeout in seconds.
        auto_auth: Automatically authenticate on first API call.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 30,
        auto_auth: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._username = username
        self._password = password
        self.timeout = timeout
        self._auto_auth = auto_auth

        self._token: str | None = None
        self._token_acquired_at: float = 0
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> str:
        """Request an authentication token from the API.

        Tries Basic Authorization header first, falls back to URL params.
        Returns the token string.
        """
        if not self._username or not self._password:
            raise VerbaAuthError(-40, "Username and password are required for authentication")

        params = {"action": "RequestToken", "apiKey": self.api_key}

        # Primary: Basic Authorization header
        credentials = f"{self._username}:{self._password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers = {"Authorization": f"Basic {encoded}"}

        response = self._session.get(
            f"{self.base_url}/api",
            params=params,
            headers=headers,
            timeout=self.timeout,
        )

        # If Basic auth fails, fall back to URL parameters
        if response.status_code != 200 or b'code="-40"' in response.content:
            logger.debug("Basic auth failed, falling back to URL parameters")
            params["userName"] = self._username
            params["password"] = self._password
            response = self._session.get(
                f"{self.base_url}/api",
                params=params,
                timeout=self.timeout,
            )

        root = self._parse_xml(response.content)
        resp_elem = root.find(".//Response")
        if resp_elem is None:
            raise VerbaAPIError(-1, "No Response element in authentication response")

        code = int(resp_elem.get("code", "-1"))
        if code != 0:
            error_msg = self._extract_error_message(root, "Authentication failed")
            raise_for_code(code, error_msg)

        self._token = resp_elem.get("token", "")
        self._token_acquired_at = time.monotonic()
        logger.info("Authenticated successfully, token acquired")
        return self._token

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def is_token_valid(self) -> bool:
        """Check if the current token is still within its lifetime."""
        if not self._token:
            return False
        elapsed = time.monotonic() - self._token_acquired_at
        return elapsed < (_TOKEN_LIFETIME - _TOKEN_REFRESH_BUFFER)

    def _ensure_token(self) -> None:
        """Authenticate if needed, or refresh if token is expired."""
        if self.is_token_valid:
            return
        if self._auto_auth:
            self.authenticate()
        else:
            raise VerbaTokenExpiredError(-43, "Token expired or missing; call authenticate()")

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    def _build_params(
        self, action: str, extra: dict[str, Any] | None = None
    ) -> list[tuple[str, str]]:
        """Build the query parameter list for an API call.

        Returns a list of (key, value) tuples to support repeated keys
        (e.g. multiple anynum values for SearchCalls).
        """
        self._ensure_token()
        params: list[tuple[str, str]] = [
            ("action", action),
            ("apiKey", self.api_key),
            ("token", self._token),
        ]
        for key, value in (extra or {}).items():
            if value is None:
                continue
            if isinstance(value, list):
                for item in value:
                    params.append((key, str(item)))
            else:
                params.append((key, str(value)))
        return params

    def _request(
        self, action: str, method: str = "GET", **kwargs: Any
    ) -> requests.Response:
        """Execute an API request and return the raw response."""
        extra_params = kwargs.pop("params", {})
        api_params = self._build_params(action, extra=extra_params)

        url = f"{self.base_url}/api"
        if method.upper() == "GET":
            resp = self._session.get(
                url, params=api_params, timeout=self.timeout, **kwargs
            )
        else:
            # For POST, query string carries auth params; body carries payload
            query_params = api_params
            data = kwargs.pop("data", None)
            resp = self._session.post(
                url, params=query_params, data=data, timeout=self.timeout, **kwargs
            )
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            raise VerbaHTTPError(e) from e
        return resp

    def _request_xml(self, action: str, **params: Any) -> ET.Element:
        """Execute an API request and return the parsed XML root.

        Automatically retries once on TOKEN_EXPIRED by re-authenticating.
        """
        try:
            resp = self._request(action, params=params)
            return self._check_xml_response(resp.content)
        except VerbaTokenExpiredError:
            logger.debug("Token expired, re-authenticating and retrying")
            self.authenticate()
            resp = self._request(action, params=params)
            return self._check_xml_response(resp.content)

    def _parse_xml(self, content: bytes) -> ET.Element:
        try:
            return ET.fromstring(content)
        except ET.ParseError as e:
            raise VerbaAPIError(-1, f"Failed to parse XML response: {e}") from e

    def _check_xml_response(self, content: bytes) -> ET.Element:
        """Parse XML and raise if the response contains an error code."""
        root = self._parse_xml(content)
        resp_elem = root.find(".//Response")
        if resp_elem is not None:
            code = int(resp_elem.get("code", "0"))
            if code != 0:
                msg = self._extract_error_message(root, "API error")
                raise_for_code(code, msg)
        return root

    @staticmethod
    def _extract_error_message(root: ET.Element, default: str = "Unknown error") -> str:
        error_elem = root.find(".//ErrorMessage")
        if error_elem is not None and error_elem.text:
            return error_elem.text.strip()
        return default

    # ------------------------------------------------------------------
    # Metadata Calls
    # ------------------------------------------------------------------

    def search_calls(
        self,
        start: str | datetime,
        end: str | datetime,
        *,
        status: str | None = None,
        anynum: str | list[str] | None = None,
        anyname: str | list[str] | None = None,
        orderby: str | None = None,
        order: str | None = None,
        pagefirst: int | None = None,
        pagelen: int | None = None,
        secondary: int | None = None,
        response_type: str = "XML",
        return_metadata: int | None = None,
        return_im: int | None = None,
        return_transcript_db: int | None = None,
        return_voice_quality: int | None = None,
        **extra_filters: str,
    ) -> SearchResult:
        """Search for call records within a time range.

        Args:
            start: Start of search period ("YYYY-MM-DD HH:MM" or datetime).
            end: End of search period ("YYYY-MM-DD HH:MM" or datetime).
            status: "ongoing" or "recorded" (default: recorded).
            anynum: Phone number(s) to filter by (caller or called).
            anyname: Name(s) to filter by.
            orderby: Field name to order results by.
            order: "asc" or "desc".
            pagefirst: Row number of the first CDR to include.
            pagelen: Number of CDRs per page.
            secondary: Set to 1 to include secondary recordings.
            response_type: "XML", "HTML", or "TEXT".
            return_metadata: Set to 1 to include custom metadata.
            return_im: Set to 1 to include IM messages.
            return_transcript_db: Set to 1 to include transcripts.
            return_voice_quality: Set to 1 to include voice quality data.
            **extra_filters: Additional f_field_name filters.

        Returns:
            SearchResult with total count and list of CallRecord objects.
        """
        if isinstance(start, datetime):
            start = start.strftime("%Y-%m-%d %H:%M")
        if isinstance(end, datetime):
            end = end.strftime("%Y-%m-%d %H:%M")

        params: dict[str, Any] = {
            "start": start,
            "end": end,
            "responseType": response_type,
        }
        if status:
            params["status"] = status
        if orderby:
            params["orderby"] = orderby
        if order:
            params["order"] = order
        if pagefirst is not None:
            params["pagefirst"] = pagefirst
        if pagelen is not None:
            params["pagelen"] = pagelen
        if secondary is not None:
            params["secondary"] = secondary
        if return_metadata is not None:
            params["returnMetadata"] = return_metadata
        if return_im is not None:
            params["returnIM"] = return_im
        if return_transcript_db is not None:
            params["returnTranscriptDB"] = return_transcript_db
        if return_voice_quality is not None:
            params["returnVoiceQuality"] = return_voice_quality
        params.update(extra_filters)

        # anynum/anyname support repeated keys -- pass as lists
        if anynum:
            params["anynum"] = [anynum] if isinstance(anynum, str) else anynum
        if anyname:
            params["anyname"] = [anyname] if isinstance(anyname, str) else anyname

        root = self._request_xml("SearchCalls", **params)
        total = int(root.get("rowcount", "0"))
        calls = [CallRecord.from_xml_element(cdr) for cdr in root.findall(".//verbacdr")]
        return SearchResult(total_count=total, calls=calls)

    def get_call_information(
        self,
        *,
        call_id: str | None = None,
        platform_call_id: str | None = None,
        native_id: str | None = None,
        meeting_id: str | None = None,
        extension: str | None = None,
        status: str | None = None,
        return_metadata: int | None = None,
        return_im: int | None = None,
        return_transcript_db: int | None = None,
        return_voice_quality: int | None = None,
    ) -> CallRecord:
        """Retrieve all metadata for a specific call.

        Provide one of: call_id, platform_call_id, native_id, meeting_id,
        or extension + status.
        """
        params: dict[str, Any] = {"responseType": "XML"}
        if call_id:
            params["callID"] = call_id
        if platform_call_id:
            params["platformCallID"] = platform_call_id
        if native_id:
            params["nativeID"] = native_id
        if meeting_id:
            params["meetingID"] = meeting_id
        if extension:
            params["extension"] = extension
        if status:
            params["status"] = status
        if return_metadata is not None:
            params["returnMetadata"] = return_metadata
        if return_im is not None:
            params["returnIM"] = return_im
        if return_transcript_db is not None:
            params["returnTranscriptDB"] = return_transcript_db
        if return_voice_quality is not None:
            params["returnVoiceQuality"] = return_voice_quality

        root = self._request_xml("GetCallInformation", **params)
        cdr = root.find(".//verbacdr")
        if cdr is None:
            # The root itself might be the verbacdr element
            if root.tag == "verbacdr":
                cdr = root
            else:
                raise VerbaAPIError(-50, "No call record found in response")
        return CallRecord.from_xml_element(cdr)

    def get_call_id(self, *, extension: str, status: str = "last") -> str:
        """Retrieve the unique call ID for a call by extension and status."""
        root = self._request_xml(
            "GetCallID", extension=extension, status=status, responseType="XML"
        )
        resp = root.find(".//Response")
        if resp is not None:
            return resp.get("callID", "")
        cdr = root.find(".//ccdr_id")
        if cdr is not None and cdr.text:
            return cdr.text.strip()
        return ""

    def get_call_url(self, *, call_id: str) -> str:
        """Retrieve the full HTTP URL pointing to a given call."""
        root = self._request_xml("GetCallURL", callID=call_id, responseType="XML")
        resp = root.find(".//Response")
        if resp is not None:
            return resp.get("url", "")
        return ""

    def delete_call(self, *, call_id: str) -> bool:
        """Delete a call or mark an ongoing call for deletion."""
        root = self._request_xml("DeleteCall", callID=call_id)
        resp = root.find(".//Response")
        if resp is not None:
            return resp.get("code", "") == "0"
        return False

    def add_marker(self, *, call_id: str, position: int, label: str = "") -> bool:
        """Add a segment marker to a recorded call."""
        params: dict[str, Any] = {"callID": call_id, "position": position}
        if label:
            params["label"] = label
        root = self._request_xml("AddMarker", **params)
        resp = root.find(".//Response")
        return resp is not None and resp.get("code", "") == "0"

    def attach_metadata(self, *, call_id: str, **metadata: str) -> bool:
        """Add metadata key-value pairs to a recorded call."""
        params: dict[str, Any] = {"callID": call_id}
        params.update(metadata)
        root = self._request_xml("AttachMetadata", **params)
        resp = root.find(".//Response")
        return resp is not None and resp.get("code", "") == "0"

    def get_markers(self, *, call_id: str) -> list[dict[str, str]]:
        """Get the list of segment markers for a recorded call."""
        root = self._request_xml("GetMarkers", callID=call_id, responseType="XML")
        markers = []
        for marker in root.findall(".//marker"):
            markers.append({
                "position": marker.get("position", ""),
                "label": marker.get("label", ""),
            })
        return markers

    def get_voice_quality(self, *, call_id: str) -> ET.Element:
        """Retrieve voice quality check results for a call. Returns raw XML element."""
        return self._request_xml("GetVoiceQuality", callID=call_id, responseType="XML")

    def keep_call(self, *, call_id: str) -> bool:
        """Keep an on-demand call (prevent auto-deletion)."""
        root = self._request_xml("KeepCall", callID=call_id)
        resp = root.find(".//Response")
        return resp is not None and resp.get("code", "") == "0"

    def mute_recording(self, *, extension: str, mute: bool = True) -> bool:
        """Mute (pause) or unmute (resume) recording for an extension."""
        action_value = "mute" if mute else "unmute"
        root = self._request_xml("MuteRecording", extension=extension, muteAction=action_value)
        resp = root.find(".//Response")
        return resp is not None and resp.get("code", "") == "0"

    # ------------------------------------------------------------------
    # Media Calls
    # ------------------------------------------------------------------

    def get_media(
        self,
        *,
        ccdr_id: str | None = None,
        extension: str | None = None,
        status: str | None = None,
    ) -> bytes:
        """Retrieve the raw media file for a call.

        Returns the raw bytes of the media file in its original format.
        Provide either ccdr_id, or extension + status.
        """
        params: dict[str, Any] = {}
        if ccdr_id:
            params["ccdr_id"] = ccdr_id
        if extension:
            params["extension"] = extension
        if status:
            params["status"] = status
        resp = self._request("GetMedia", params=params)
        return resp.content

    def get_media_encoded(
        self,
        *,
        ccdr_id: str | None = None,
        extension: str | None = None,
        status: str | None = None,
        codec: str | None = None,
    ) -> bytes:
        """Retrieve encoded media for a call. Returns raw bytes."""
        params: dict[str, Any] = {}
        if ccdr_id:
            params["ccdr_id"] = ccdr_id
        if extension:
            params["extension"] = extension
        if status:
            params["status"] = status
        if codec:
            params["codec"] = codec
        resp = self._request("GetMediaEncoded", params=params)
        return resp.content

    def get_media_live(
        self, *, extension: str, status: str = "ongoing"
    ) -> bytes:
        """Retrieve live media for an ongoing call."""
        resp = self._request("GetMediaLive", params={"extension": extension, "status": status})
        return resp.content

    def get_media_segment(
        self,
        *,
        ccdr_id: str,
        start_ms: int,
        end_ms: int,
    ) -> bytes:
        """Retrieve an audio segment of a call between start_ms and end_ms."""
        resp = self._request(
            "GetMediaSegment",
            params={"ccdr_id": ccdr_id, "start": start_ms, "end": end_ms},
        )
        return resp.content

    def get_thumbnail(self, *, ccdr_id: str, position: int = 0) -> bytes:
        """Retrieve a video frame thumbnail from a video call."""
        resp = self._request(
            "GetThumbnail", params={"ccdr_id": ccdr_id, "position": position}
        )
        return resp.content

    def get_waveform(self, *, ccdr_id: str) -> bytes:
        """Retrieve the waveform image for a call."""
        resp = self._request("GetWaveform", params={"ccdr_id": ccdr_id})
        return resp.content

    def put_media(self, *, media_data: bytes, **metadata: str) -> bool:
        """Upload a media file with metadata.

        Uses _request_xml() pipeline for automatic token-retry on upload.
        """
        params: dict[str, Any] = dict(metadata)

        try:
            resp = self._request("PutMedia", method="POST", params=params, data=media_data)
            root = self._check_xml_response(resp.content)
        except VerbaTokenExpiredError:
            logger.debug("Token expired during upload, re-authenticating and retrying")
            self.authenticate()
            resp = self._request("PutMedia", method="POST", params=params, data=media_data)
            root = self._check_xml_response(resp.content)

        resp_elem = root.find(".//Response")
        return resp_elem is not None and resp_elem.get("code", "") == "0"

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> VerbaClient:
        if self._auto_auth and not self.is_token_valid:
            self.authenticate()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._session.close()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
