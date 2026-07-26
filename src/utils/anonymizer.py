"""PII scrubbing for support bundle content.

Replaces IP addresses, MAC addresses, device/preset names, device UUIDs, and
home-directory usernames found in log text and settings/capabilities JSON
with random per-value tokens. The same real value always maps to the same
token *within one bundle* (one :class:`BundleAnonymizer` instance), so a
support engineer can still correlate "this is the same device/preset" across
log lines without being able to identify the real value. The mapping is not
seeded or persisted -- each new instance (each bundle generation) produces a
fresh, unrelated set of tokens.
"""

from __future__ import annotations

import re
import secrets

# Structural patterns with near-zero false-positive risk.
_IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_MAC_RE = re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b")

# Home-directory path prefixes; only the username segment is captured/replaced.
_WINDOWS_USER_RE = re.compile(r"(?<=[Uu]sers\\)[^\\/:*\"<>|]+")
_POSIX_HOME_USER_RE = re.compile(r"(?<=/home/)[^/]+")
_MAC_HOME_USER_RE = re.compile(r"(?<=/Users/)[^/]+")

# JSON keys (as they appear on the wire) whose string values are PII.
_PII_JSON_KEYS = (
    "DeviceName",
    "Name",
    "newName",
    "GroupName",
    "mac_address",
    "uuid",
)
_PII_JSON_KEY_RE = re.compile(
    r'"(' + "|".join(re.escape(k) for k in _PII_JSON_KEYS) + r')"(\s*:\s*)"([^"]*)"'
)


class BundleAnonymizer:
    """Scrubs PII from support-bundle text/JSON with per-value random tokens.

    One instance should be shared across every file added to a single
    support bundle so the same real value maps to the same token throughout.
    """

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str] = {}

    def _token_for(self, category: str, raw_value: str) -> str:
        """Return the (cached or newly-generated) token for a raw PII value."""
        if not raw_value:
            return raw_value
        key = (category, raw_value)
        token = self._tokens.get(key)
        if token is None:
            token = f"{category}-{secrets.token_hex(4)}"
            self._tokens[key] = token
        return token

    def anonymize_text(self, text: str) -> str:
        """Scrub PII from free-form text (e.g. a log file's full content)."""
        text = _IPV4_RE.sub(lambda m: self._token_for("IP", m.group(0)), text)
        text = _MAC_RE.sub(lambda m: self._token_for("MAC", m.group(0)), text)
        text = _WINDOWS_USER_RE.sub(
            lambda m: self._token_for("USER", m.group(0)), text
        )
        text = _POSIX_HOME_USER_RE.sub(
            lambda m: self._token_for("USER", m.group(0)), text
        )
        text = _MAC_HOME_USER_RE.sub(
            lambda m: self._token_for("USER", m.group(0)), text
        )
        text = _PII_JSON_KEY_RE.sub(
            lambda m: f'"{m.group(1)}"{m.group(2)}"'
            f'{self._token_for("NAME", m.group(3))}"',
            text,
        )
        return text

    def anonymize_json_value(self, data: object) -> object:
        """Recursively scrub PII from a parsed JSON-like structure (dict/list/str)."""
        if isinstance(data, dict):
            result: dict[str, object] = {}
            for k, v in data.items():
                if k in _PII_JSON_KEYS and isinstance(v, str):
                    result[k] = self._token_for("NAME", v)
                elif k == "source_names" and isinstance(v, list):
                    result[k] = [
                        self._token_for("NAME", item) if isinstance(item, str) else item
                        for item in v
                    ]
                elif k == "source_aliases" and isinstance(v, dict):
                    result[k] = {
                        alias_key: self._token_for("NAME", alias_val)
                        if isinstance(alias_val, str)
                        else alias_val
                        for alias_key, alias_val in v.items()
                    }
                else:
                    result[k] = self.anonymize_json_value(v)
            return result
        if isinstance(data, list):
            return [self.anonymize_json_value(item) for item in data]
        if isinstance(data, str):
            return self.anonymize_text(data)
        return data
