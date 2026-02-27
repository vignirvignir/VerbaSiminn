"""Verba API error codes mapped to exceptions.

Error code reference (from API docs):
  -1:  UNEXPECTED_ERROR
  -10: EVALUATION_EXPIRED
  -20: INVALID_PARAMETERS
  -30: INVALID_ACTION
  -40: INVALID_CREDENTIALS
  -41: INVALID_API_KEY
  -42: LOGIN_REQUIRED
  -43: TOKEN_EXPIRED
  -50: CALL_NOT_FOUND
  -60: INVALID_BUSINESS_ID
  -70: MEDIA_NOT_FOUND
  -71: VIDEO_NOT_FOUND
  -80: PROPERTY_NOT_FOUND
"""


class VerbaAPIError(Exception):
    """Base exception for all Verba API errors."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class VerbaAuthError(VerbaAPIError):
    """Authentication failure (-40, -41, -42)."""


class VerbaTokenExpiredError(VerbaAPIError):
    """Token has expired (-43)."""


class VerbaInvalidParametersError(VerbaAPIError):
    """Invalid or missing parameters (-20)."""


class VerbaCallNotFoundError(VerbaAPIError):
    """Requested call not found (-50)."""


class VerbaMediaNotFoundError(VerbaAPIError):
    """Requested media/video not found (-70, -71)."""


class VerbaHTTPError(VerbaAPIError):
    """Wraps requests.HTTPError so consumers only catch VerbaAPIError."""

    def __init__(self, http_error: Exception):
        self.http_error = http_error
        response = getattr(http_error, "response", None)
        status_code = response.status_code if response is not None else 0
        super().__init__(-1, f"HTTP {status_code}: {http_error}")


# Maps API error codes to exception classes
ERROR_CODE_MAP: dict[int, type[VerbaAPIError]] = {
    -1: VerbaAPIError,
    -10: VerbaAPIError,
    -20: VerbaInvalidParametersError,
    -30: VerbaAPIError,
    -40: VerbaAuthError,
    -41: VerbaAuthError,
    -42: VerbaAuthError,
    -43: VerbaTokenExpiredError,
    -50: VerbaCallNotFoundError,
    -60: VerbaAPIError,
    -70: VerbaMediaNotFoundError,
    -71: VerbaMediaNotFoundError,
    -80: VerbaAPIError,
}


def raise_for_code(code: int, message: str) -> None:
    """Raise the appropriate exception for an API error code."""
    exc_class = ERROR_CODE_MAP.get(code, VerbaAPIError)
    raise exc_class(code, message)
