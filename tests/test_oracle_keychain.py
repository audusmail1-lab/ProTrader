"""Native Keychain contract checks with fictional keys and mocked frameworks."""
import ctypes
import importlib.util
import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location("oracle_keychain_under_test", Path(__file__).resolve().parents[1] / "scripts/oracle_keychain.py")
keychain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(keychain)
KEY = "fictional-key-only"
AGENT = "agent_test_fixture"


class OracleKeychainTests(unittest.TestCase):
    def setUp(self):
        self.native = Mock()
        self.native.security.SecKeychainFindGenericPassword.return_value = keychain._NOT_FOUND
        self.native.security.SecKeychainAddGenericPassword.return_value = 0
        self.native.security.SecKeychainItemModifyAttributesAndData.return_value = 0
        self.patch = patch.object(keychain, "_NativeKeychain", return_value=self.native)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def found_data(self, value):
        self.data_buffer = ctypes.create_string_buffer(value)
        def find(*args):
            ctypes.cast(args[5], ctypes.POINTER(ctypes.c_uint32))[0] = len(value)
            ctypes.cast(args[6], ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(self.data_buffer)
            return 0
        return find

    def found_item(self, *args):
        self.assertIsNone(args[5])
        self.assertIsNone(args[6])
        ctypes.cast(args[7], ctypes.POINTER(ctypes.c_void_p))[0] = 12345
        return 0

    def assert_identity(self, args):
        self.assertIsNone(args[0])
        self.assertEqual(args[1:5], (len(keychain.SERVICE.encode()), keychain.SERVICE.encode(), len(AGENT.encode()), AGENT.encode()))

    def test_missing_item_is_none_without_freeing_unallocated_data(self):
        self.assertIsNone(keychain.read_key(AGENT))
        self.assert_identity(self.native.security.SecKeychainFindGenericPassword.call_args.args)
        self.native.security.SecKeychainItemFreeContent.assert_not_called()

    def test_read_uses_length_and_frees_native_data(self):
        self.native.security.SecKeychainFindGenericPassword.side_effect = self.found_data(KEY.encode())
        self.assertEqual(keychain.read_key(AGENT), KEY)
        self.native.security.SecKeychainItemFreeContent.assert_called_once()
        args = self.native.security.SecKeychainItemFreeContent.call_args.args
        self.assertIsNone(args[0])
        self.assertEqual(args[1].value, ctypes.addressof(self.data_buffer))
        self.native.core.CFRelease.assert_not_called()

    def test_decode_error_is_sanitized_and_still_frees_data(self):
        self.native.security.SecKeychainFindGenericPassword.side_effect = self.found_data(b"\xffsecret")
        with self.assertRaisesRegex(keychain.KeychainError, "saved key could not be read") as result:
            keychain.read_key(AGENT)
        self.assertNotIn("secret", str(result.exception))
        self.assertIsNone(result.exception.__cause__)
        self.native.security.SecKeychainItemFreeContent.assert_called_once()

    def test_bad_native_lengths_do_not_read_memory_and_still_free(self):
        for length in (0, keychain._MAX_KEY_BYTES + 1):
            def find(*args):
                ctypes.cast(args[5], ctypes.POINTER(ctypes.c_uint32))[0] = length
                ctypes.cast(args[6], ctypes.POINTER(ctypes.c_void_p))[0] = 12345
                return 0
            self.native.security.SecKeychainFindGenericPassword.side_effect = find
            with self.subTest(length=length), patch.object(keychain.ctypes, "string_at") as read:
                with self.assertRaises(keychain.KeychainError):
                    keychain.read_key(AGENT)
                read.assert_not_called()
        self.assertEqual(self.native.security.SecKeychainItemFreeContent.call_count, 2)

    def test_denied_or_unavailable_read_never_becomes_missing_or_writes(self):
        for code in (-128, -25293, -25308, -25291, -123):
            with self.subTest(code=code):
                self.native.security.SecKeychainFindGenericPassword.return_value = code
                with self.assertRaises(keychain.KeychainError):
                    keychain.read_key(AGENT)
        self.native.security.SecKeychainAddGenericPassword.assert_not_called()
        self.native.security.SecKeychainItemModifyAttributesAndData.assert_not_called()

    def test_save_new_key_uses_native_buffer_then_clears_it(self):
        observed = []
        def add(*args):
            self.assert_identity(args)
            self.assertEqual(ctypes.string_at(args[6], args[5]), KEY.encode())
            observed.append(args[6])
            return 0
        self.native.security.SecKeychainAddGenericPassword.side_effect = add
        keychain.save_key(AGENT, KEY)
        self.assertEqual(observed[0].raw, b"\x00" * (len(KEY) + 1))
        self.native.security.SecKeychainItemModifyAttributesAndData.assert_not_called()
        self.native.core.CFRelease.assert_not_called()

    def test_save_updates_exact_item_without_changing_attributes_or_adding(self):
        self.native.security.SecKeychainFindGenericPassword.side_effect = self.found_item
        def modify(item, attrs, length, data):
            self.assertEqual(item.value, 12345)
            self.assertIsNone(attrs)
            self.assertEqual(ctypes.string_at(data, length), KEY.encode())
            return 0
        self.native.security.SecKeychainItemModifyAttributesAndData.side_effect = modify
        keychain.save_key(AGENT, KEY)
        self.native.security.SecKeychainAddGenericPassword.assert_not_called()
        self.native.core.CFRelease.assert_called_once()
        self.assertEqual(self.native.core.CFRelease.call_args.args[0].value, 12345)

    def test_failed_update_releases_item_and_never_deletes_or_replaces(self):
        self.native.security.SecKeychainFindGenericPassword.side_effect = self.found_item
        self.native.security.SecKeychainItemModifyAttributesAndData.return_value = -25293
        with self.assertRaises(keychain.KeychainError):
            keychain.save_key(AGENT, KEY)
        self.native.core.CFRelease.assert_called_once()
        self.native.security.SecKeychainAddGenericPassword.assert_not_called()
        self.native.security.SecKeychainItemDelete.assert_not_called()
        data = self.native.security.SecKeychainItemModifyAttributesAndData.call_args.args[3]
        self.assertEqual(data.raw, b"\x00" * (len(KEY) + 1))

    def test_denied_lookup_does_not_create_a_second_key(self):
        self.native.security.SecKeychainFindGenericPassword.return_value = -25308
        with self.assertRaises(keychain.KeychainError):
            keychain.save_key(AGENT, KEY)
        self.native.security.SecKeychainAddGenericPassword.assert_not_called()
        self.native.security.SecKeychainItemModifyAttributesAndData.assert_not_called()

    def test_duplicate_race_rechecks_exact_item_once_then_updates(self):
        def find(*args):
            if self.native.security.SecKeychainFindGenericPassword.call_count == 1:
                return keychain._NOT_FOUND
            self.assert_identity(args)
            return self.found_item(*args)
        self.native.security.SecKeychainFindGenericPassword.side_effect = find
        self.native.security.SecKeychainAddGenericPassword.return_value = keychain._DUPLICATE
        keychain.save_key(AGENT, KEY)
        self.assertEqual(self.native.security.SecKeychainFindGenericPassword.call_count, 2)
        self.native.security.SecKeychainAddGenericPassword.assert_called_once()
        self.native.security.SecKeychainItemModifyAttributesAndData.assert_called_once()
        self.native.core.CFRelease.assert_called_once()

    def test_duplicate_race_failure_is_bounded(self):
        self.native.security.SecKeychainAddGenericPassword.return_value = keychain._DUPLICATE
        with self.assertRaises(keychain.KeychainError):
            keychain.save_key(AGENT, KEY)
        self.assertEqual(self.native.security.SecKeychainFindGenericPassword.call_count, 2)
        self.native.security.SecKeychainAddGenericPassword.assert_called_once()
        self.native.security.SecKeychainItemModifyAttributesAndData.assert_not_called()

    def test_invalid_inputs_are_sanitized_and_never_reach_os(self):
        for invalid in ("", None, "nul\x00agent", "x" * 1025, "\ud800"):
            with self.subTest(agent=repr(invalid)), self.assertRaises(keychain.KeychainError):
                keychain.read_key(invalid)
        for invalid in ("", None, "secret\x00suffix", "x" * (keychain._MAX_KEY_BYTES + 1), "\ud800"):
            with self.subTest(key=type(invalid)), self.assertRaises(keychain.KeychainError):
                keychain.save_key(AGENT, invalid)
        keychain._NativeKeychain.assert_not_called()

    def test_no_key_output_on_success_or_error(self):
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
            keychain.save_key(AGENT, KEY)
            self.native.security.SecKeychainFindGenericPassword.return_value = -128
            with self.assertRaises(keychain.KeychainError) as result:
                keychain.save_key(AGENT, KEY)
        self.assertEqual(output.getvalue() + errors.getvalue(), "")
        self.assertNotIn(KEY, str(result.exception))


class NativeFrameworkLoadingTests(unittest.TestCase):
    def test_unsupported_platform_does_not_attempt_library_load(self):
        with patch.object(keychain.sys, "platform", "linux"), patch.object(keychain.ctypes, "CDLL") as load:
            with self.assertRaisesRegex(keychain.KeychainError, "macOS only"):
                keychain._NativeKeychain()
        load.assert_not_called()

    def test_framework_errors_are_sanitized(self):
        for error in (OSError(KEY), AttributeError(KEY)):
            with self.subTest(error=type(error)), patch.object(keychain.sys, "platform", "darwin"), \
                    patch.object(keychain.ctypes, "CDLL", side_effect=error):
                with self.assertRaises(keychain.KeychainError) as result:
                    keychain._NativeKeychain()
                self.assertNotIn(KEY, str(result.exception))
                self.assertIsNone(result.exception.__cause__)

    def test_framework_functions_have_explicit_pointer_safe_signatures(self):
        security, core = Mock(), Mock()
        with patch.object(keychain.sys, "platform", "darwin"), \
                patch.object(keychain.ctypes, "CDLL", side_effect=[security, core]):
            keychain._NativeKeychain()
        self.assertIs(security.SecKeychainFindGenericPassword.restype, ctypes.c_int32)
        self.assertEqual(security.SecKeychainFindGenericPassword.argtypes[-1], ctypes.POINTER(ctypes.c_void_p))
        self.assertEqual(security.SecKeychainItemModifyAttributesAndData.argtypes, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p])
        self.assertEqual(core.CFRelease.argtypes, [ctypes.c_void_p])
        self.assertIsNone(core.CFRelease.restype)


if __name__ == "__main__":
    unittest.main()
