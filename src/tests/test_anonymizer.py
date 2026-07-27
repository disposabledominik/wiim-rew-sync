"""Unit tests for src/utils/anonymizer.py.

Covers:
  1. Structural patterns (IP, MAC) get scrubbed and are consistent
  2. PII JSON keys (DeviceName, Name, uuid, ...) get scrubbed in text and dicts
  3. Home-directory usernames get scrubbed, rest of path preserved
  4. Consistency within one instance, no cross-instance determinism
  5. Non-PII content passes through unchanged
"""

from __future__ import annotations

from src.utils.anonymizer import BundleAnonymizer


class TestIpAndMac:
    def test_ip_is_scrubbed(self) -> None:
        anon = BundleAnonymizer()
        result = anon.anonymize_text("REQ #1 -> GET https://192.168.1.42/httpapi.asp")
        assert "192.168.1.42" not in result
        assert "IP-" in result

    def test_same_ip_maps_to_same_token(self) -> None:
        anon = BundleAnonymizer()
        text = "first 192.168.1.42 then later 192.168.1.42 again"
        result = anon.anonymize_text(text)
        tokens = {word for word in result.split() if word.startswith("IP-")}
        assert len(tokens) == 1

    def test_different_ips_map_to_different_tokens(self) -> None:
        anon = BundleAnonymizer()
        result = anon.anonymize_text("192.168.1.1 and 192.168.1.2")
        tokens = {word for word in result.split() if word.startswith("IP-")}
        assert len(tokens) == 2

    def test_mac_is_scrubbed(self) -> None:
        anon = BundleAnonymizer()
        result = anon.anonymize_text("mac AA:BB:CC:DD:EE:FF seen")
        assert "AA:BB:CC:DD:EE:FF" not in result
        assert "MAC-" in result

    def test_same_mac_maps_to_same_token(self) -> None:
        anon = BundleAnonymizer()
        text = "AA:BB:CC:DD:EE:FF ... AA:BB:CC:DD:EE:FF"
        result = anon.anonymize_text(text)
        tokens = {w for w in result.replace("...", " ").split() if w.startswith("MAC-")}
        assert len(tokens) == 1


class TestJsonKeyValues:
    def test_device_name_scrubbed_in_text(self) -> None:
        anon = BundleAnonymizer()
        body = '{"DeviceName":"Living Room","uuid":"FF31F09E0000"}'
        result = anon.anonymize_text(body)
        assert "Living Room" not in result
        assert "FF31F09E0000" not in result
        assert '"DeviceName":"NAME-' in result
        assert '"uuid":"NAME-' in result

    def test_same_name_consistent_across_occurrences(self) -> None:
        anon = BundleAnonymizer()
        body = '{"Name":"My Preset"} ... {"newName":"My Preset"}'
        result = anon.anonymize_text(body)
        tokens = set()
        for part in result.split("..."):
            for key in ('"Name":"', '"newName":"'):
                if key in part:
                    tokens.add(part.split(key)[1].split('"')[0])
        assert len(tokens) == 1

    def test_dict_values_scrubbed(self) -> None:
        anon = BundleAnonymizer()
        data = {
            "supports_peq": True,
            "max_filters": 10,
            "DeviceName": "Living Room",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "source_names": ["Living Room Input"],
        }
        result = anon.anonymize_json_value(data)
        assert isinstance(result, dict)
        assert result["supports_peq"] is True
        assert result["max_filters"] == 10
        assert result["DeviceName"] != "Living Room"
        assert result["DeviceName"].startswith("NAME-")
        assert result["mac_address"] != "AA:BB:CC:DD:EE:FF"
        assert "Living Room" not in result["source_names"][0]

    def test_nested_dict_values_scrubbed(self) -> None:
        anon = BundleAnonymizer()
        data = {"outer": {"uuid": "FF31F09E0000"}}
        result = anon.anonymize_json_value(data)
        assert isinstance(result, dict)
        outer = result["outer"]
        assert isinstance(outer, dict)
        assert outer["uuid"] != "FF31F09E0000"

    def test_same_value_same_token_across_text_and_dict(self) -> None:
        anon = BundleAnonymizer()
        text_result = anon.anonymize_text('"DeviceName":"Living Room"')
        dict_result = anon.anonymize_json_value({"DeviceName": "Living Room"})
        assert isinstance(dict_result, dict)
        token_from_text = text_result.split('"DeviceName":"')[1].split('"')[0]
        assert dict_result["DeviceName"] == token_from_text


class TestHomeDirectoryUsernames:
    def test_windows_username_scrubbed(self) -> None:
        anon = BundleAnonymizer()
        result = anon.anonymize_text(r"C:\Users\John\rew-exports\file.txt")
        assert "John" not in result
        assert "USER-" in result
        assert "rew-exports" in result
        assert "file.txt" in result

    def test_posix_home_username_scrubbed(self) -> None:
        anon = BundleAnonymizer()
        result = anon.anonymize_text("/home/dominik/rew-exports/file.txt")
        assert "dominik" not in result
        assert "USER-" in result
        assert "rew-exports" in result

    def test_mac_home_username_scrubbed(self) -> None:
        anon = BundleAnonymizer()
        result = anon.anonymize_text("/Users/dominik/rew-exports/file.txt")
        assert "dominik" not in result
        assert "USER-" in result
        assert "rew-exports" in result

    def test_json_escaped_windows_username_scrubbed(self) -> None:
        """A Windows path as it actually appears in a JSON file on disk has
        each backslash escaped as "\\\\", not a single backslash."""
        anon = BundleAnonymizer()
        raw_json = r'{"rew_folder": "C:\\Users\\John\\rew-exports"}'
        result = anon.anonymize_text(raw_json)
        assert "John" not in result
        assert "USER-" in result
        assert "rew-exports" in result


class TestMacAddressTokenConsistency:
    def test_mac_address_same_token_via_text_and_json_paths(self) -> None:
        """A MAC address must map to the same token whether it's scrubbed via
        anonymize_text() (raw log line) or anonymize_json_value() (a
        capabilities dict's mac_address field) -- both use the "MAC" token
        category, not two different categories for the same real value."""
        anon = BundleAnonymizer()
        mac = "AA:BB:CC:DD:EE:FF"
        text_result = anon.anonymize_text(f"seen mac {mac}")
        dict_result = anon.anonymize_json_value({"mac_address": mac})
        assert isinstance(dict_result, dict)
        text_token = text_result.split("seen mac ")[1]
        assert dict_result["mac_address"] == text_token
        assert text_token.startswith("MAC-")

    def test_mac_address_json_field_embedded_in_log_text_keeps_mac_token(self) -> None:
        """A log line dumping a raw response body (e.g. wiim_api.log's
        RESP #n <- ... body={"mac_address": "..."} ) must scrub the MAC to
        the same "MAC-" token as a bare occurrence -- not have _PII_JSON_KEY_RE
        re-match the already-substituted placeholder and overwrite it with a
        "NAME-" token."""
        anon = BundleAnonymizer()
        mac = "AA:BB:CC:DD:EE:FF"
        bare_result = anon.anonymize_text(f"seen mac {mac}")
        embedded_result = anon.anonymize_text(f'{{"mac_address":"{mac}"}}')
        bare_token = bare_result.split("seen mac ")[1]
        embedded_token = embedded_result.split('"mac_address":"')[1].rstrip('"}')
        assert bare_token == embedded_token
        assert embedded_token.startswith("MAC-")


class TestConsistencyAndIsolation:
    def test_different_instances_produce_different_tokens(self) -> None:
        anon_a = BundleAnonymizer()
        anon_b = BundleAnonymizer()
        result_a = anon_a.anonymize_text("192.168.1.42")
        result_b = anon_b.anonymize_text("192.168.1.42")
        assert result_a != result_b

    def test_non_pii_content_passes_through_unchanged(self) -> None:
        anon = BundleAnonymizer()
        text = "RESP #3 <- 200 (len=42) body={\"status\":\"OK\",\"gain\":3.5}"
        result = anon.anonymize_text(text)
        assert result == text

    def test_empty_string_untouched(self) -> None:
        anon = BundleAnonymizer()
        assert anon.anonymize_text("") == ""
