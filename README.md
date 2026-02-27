# verba-client

Python client for the [Verba (VFC Capture)](https://verbalabs.atlassian.net/wiki/spaces/docs/) HTTP Business API.

## Installation

```bash
pip install verba-client
```

## Quick Start

```python
from datetime import datetime, timedelta
from verba_client import VerbaClient

with VerbaClient(
    base_url="https://your-verba-server.com/verba",
    api_key="YOUR-API-KEY",
    username="user@example.com",
    password="password",
) as client:
    # Search calls from the last 7 days
    end = datetime.now()
    start = end - timedelta(days=7)
    result = client.search_calls(start, end, pagelen=50)

    print(f"Found {result.total_count} calls")
    for call in result.calls:
        print(f"  {call.ccdr_id}: {call.source_caller_id} -> {call.destination_caller_id}")
```

## API Coverage

All 18 HTTP Business API endpoints are supported:

**Authentication:** `authenticate()`

**Metadata Calls:**
`search_calls()`, `get_call_information()`, `get_call_id()`, `get_call_url()`,
`delete_call()`, `add_marker()`, `attach_metadata()`, `get_markers()`,
`get_voice_quality()`, `keep_call()`, `mute_recording()`

**Media Calls:**
`get_media()`, `get_media_encoded()`, `get_media_live()`, `get_media_segment()`,
`get_thumbnail()`, `get_waveform()`, `put_media()`

## License

MIT
