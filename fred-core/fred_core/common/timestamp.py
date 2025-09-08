# Copyright Thales 2025
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Fred canonical time handling

Quick dev guide:

1. Inside models and code → always keep fields as datetime (tz-aware UTC).
   - default now:      utc_now()
   - normalize input:  timestamp(value, as_datetime=True)

2. On the wire (DB, JSON, logs) → always serialize to ISO-8601 'Z'.
   - convert:          timestamp(dt)
   - now as string:    iso_now()

3. Precision is seconds (no micros) for stability across DB/UI.

Typical examples:
-----------------
>>> # In a Pydantic model
>>> created_at: datetime = Field(default_factory=utc_now)

>>> # Normalize incoming field
>>> @field_validator("created", mode="before")
... def normalize(cls, v): return timestamp(v, as_datetime=True)

>>> # Build dict for DB / logs
>>> {"@timestamp": timestamp(event.timestamp)}

>>> # Quick event log line
>>> logger.info("start=%s end=%s", iso_now(), iso_now())
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Union, Literal, overload

ISOInput = Union[datetime, str, None]

@overload
def timestamp(value: ISOInput = None, *, as_datetime: Literal[True]) -> datetime: ...
@overload
def timestamp(value: ISOInput = None, *, as_datetime: Literal[False] = ...) -> str: ...
@overload
def timestamp(value: ISOInput = None, *, as_datetime: bool = ...) -> Union[str, datetime]: ...

def timestamp(value: ISOInput = None, *, as_datetime: bool = False) -> Union[str, datetime]:
    """
    Canonical converter:

    - Input: None | datetime (naive or aware) | ISO string (with 'Z' or offset)
    - Normalizes to UTC and strips microseconds.
    - Returns datetime if as_datetime=True, else ISO-8601 string with 'Z'.
    """

    if value is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    elif isinstance(value, str):
        txt = value.strip().replace(" ", "T")
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(txt)
        except ValueError as e:
            raise ValueError(f"Invalid ISO datetime: {value}") from e
        dt = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)

    dt = dt.replace(microsecond=0)
    return dt if as_datetime else dt.isoformat().replace("+00:00", "Z")

def utc_now() -> datetime:
    """Canonical UTC datetime (seconds precision)."""
    return timestamp(as_datetime=True)  # type: ignore

def iso_now() -> str:
    """Canonical UTC ISO string with 'Z' (seconds precision)."""
    return timestamp()  # type: ignore
