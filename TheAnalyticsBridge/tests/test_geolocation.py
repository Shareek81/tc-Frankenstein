import unittest

import httpx

from integrations.geolocation import IpGeolocation


class GeolocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_public_addresses_never_leave_machine(self):
        def unexpected(request):
            self.fail("Non-public address sent to provider")

        resolver = IpGeolocation(transport=httpx.MockTransport(unexpected))
        for address in ("192.168.1.1", "10.0.0.5", "127.0.0.1", "192.0.2.1", "::1", "ff02::1"):
            self.assertEqual((await resolver.locate(address)).status, "non_public")
        with self.assertRaises(ValueError):
            await resolver.locate("localhost/path")

    async def test_location_is_validated_and_cached(self):
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={"ip": "8.8.8.8", "success": True,
                "latitude": 37.4, "longitude": -122.1, "city": "Mountain View", "country": "United States"})

        resolver = IpGeolocation(transport=httpx.MockTransport(respond))
        first = await resolver.locate("8.8.8.8")
        self.assertEqual(first.status, "located")
        self.assertEqual(first.longitude, -122.1)
        self.assertEqual(await resolver.locate("8.8.8.8"), first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].url.host, "ipwho.is")

    async def test_unknown_and_failed_provider_responses(self):
        resolver = IpGeolocation(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"success": False})))
        self.assertEqual((await resolver.locate("8.8.8.8")).status, "unknown")
        for payload in ({}, [], {"ip": "8.8.8.8", "success": True, "latitude": 91, "longitude": 1},
                        {"ip": "8.8.8.8", "success": True, "latitude": True, "longitude": 1}):
            resolver = IpGeolocation(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
            with self.assertRaises(ValueError):
                await resolver.locate("8.8.8.8")
        resolver = IpGeolocation(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
        with self.assertRaises(httpx.HTTPStatusError):
            await resolver.locate("8.8.8.8")