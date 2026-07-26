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

# Home-directory path prefixes (Windows/Linux/macOS); the prefix is captured
# so it can be re-emitted as-is, with only the username segment replaced.
# The Windows separator matches one OR two backslashes: settings.json (and
# any other JSON blob) stores a Windows path with each backslash escaped as
# "\\\\", so a real single-backslash "Users\" in the raw file text is a
# literal double backslash on disk -- matching only a single backslash here
# would silently fail to scrub the username on every Windows settings.json.
_HOME_USER_RE = re.compile(r"([Uu]sers\\{1,2}|/home/|/Users/)([^\\/:*\"<>|]+)")

# JSON keys (as they appear on the wire) whose values are PII: a bare string
# for most, but a list of names for "source_names" and a dict of names for
# "source_aliases" -- anonymize_json_value's _as_name() handles all three
# shapes uniformly.
_PII_JSON_KEYS = (
    "DeviceName",
    "Name",
    "newName",
    "GroupName",
    "mac_address",
    "uuid",
    "source_names",
    "source_aliases",
)
# Text-log scrubbing only ever sees bare string values (log lines are prose
# with embedded JSON snippets, not standalone documents to parse), so this
# pattern targets the scalar-valued keys only.
_PII_JSON_KEY_RE = re.compile(
    r'("(?:'
    + "|".join(re.escape(k) for k in _PII_JSON_KEYS if k not in ("source_names", "source_aliases"))
    + r')"\s*:\s*)"([^"]*)"'
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
        text = _HOME_USER_RE.sub(
            lambda m: m.group(1) + self._token_for("USER", m.group(2)), text
        )
        text = _PII_JSON_KEY_RE.sub(
            lambda m: f'{m.group(1)}"{self._token_for("NAME", m.group(2))}"', text
        )
        return text

    def _as_name(self, value: object) -> object:
        """Recursively token-ize every string found in *value*.

        Handles all three shapes a name field appears in on the wire: a bare
        string (``DeviceName``), a list of strings (``source_names``), or a
        dict of strings (``source_aliases``).
        """
        if isinstance(value, str):
            return self._token_for("NAME", value)
        if isinstance(value, list):
            return [self._as_name(item) for item in value]
        if isinstance(value, dict):
            return {k: self._as_name(v) for k, v in value.items()}
        return value

    def anonymize_json_value(self, data: object) -> object:
        """Recursively scrub PII from a parsed JSON-like structure (dict/list/str)."""
        if isinstance(data, dict):
            result: dict[str, object] = {}
            for k, v in data.items():
                if k == "mac_address" and isinstance(v, str):
                    # Same category ("MAC") as the structural regex used on
                    # log text, so a MAC address that appears both here (a
                    # dict field) and in a raw log line maps to the same
                    # token throughout the bundle -- routing it through
                    # _as_name's "NAME" category instead would give the same
                    # real MAC two different tokens depending on which path
                    # scrubbed it.
                    result[k] = self._token_for("MAC", v)
                elif k in _PII_JSON_KEYS:
                    result[k] = self._as_name(v)
                else:
                    result[k] = self.anonymize_json_value(v)
            return result
        if isinstance(data, list):
            return [self.anonymize_json_value(item) for item in data]
        if isinstance(data, str):
            return self.anonymize_text(data)
        return data
