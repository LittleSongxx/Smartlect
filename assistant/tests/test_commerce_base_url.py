"""SMARTLECT_JAVA_BASE_URL de-hardcodes the loopback transport; default keeps it."""
import unittest

from smartlect.commerce import AsyncCommerceClient, CommerceClient


class CommerceBaseUrlTests(unittest.TestCase):
    def test_default_is_loopback_and_override_wins(self):
        default = AsyncCommerceClient({"SMARTLECT_USER_PORT": "18082"})
        self.assertEqual(default._service_url("user", "/internal/x"),
                         "http://127.0.0.1:18082/internal/x")
        configured = AsyncCommerceClient({"SMARTLECT_USER_PORT": "18082",
                                          "SMARTLECT_JAVA_BASE_URL": "http://10.0.0.8/"})
        self.assertEqual(configured._service_url("user", "/internal/x"),
                         "http://10.0.0.8:18082/internal/x")

    def test_sync_client_builds_url_from_base(self):
        client = CommerceClient({"SMARTLECT_ORDER_PORT": "18086",
                                 "SMARTLECT_JAVA_BASE_URL": "http://java.internal"})
        self.assertEqual(client._base_host, "http://java.internal")


if __name__ == '__main__':
    unittest.main()
