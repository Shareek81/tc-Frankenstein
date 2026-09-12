import asyncio
import ssl
from collections import OrderedDict
from ipaddress import ip_address
from time import monotonic

import httpx
from pydantic import BaseModel, Field


class IpLocation(BaseModel):
    ip: str
    status: str
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    city: str = ""
    country: str = ""


class IpGeolocation:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._cache: OrderedDict[str, tuple[float, IpLocation]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def locate(self, value: str) -> IpLocation:
        address = ip_address(value)
        canonical = str(address)
        if not address.is_global or address.is_multicast:
            return IpLocation(ip=canonical, status="non_public")
        async with self._lock:
            cached = self._cache.get(canonical)
            if cached and monotonic() - cached[0] < 3600:
                self._cache.move_to_end(canonical)
                return cached[1]
            async with httpx.AsyncClient(
                transport=self._transport, timeout=8, verify=ssl.create_default_context(),
            ) as client:
                response = await client.get(
                    f"https://ipwho.is/{canonical}",
                    params={"fields": "ip,success,latitude,longitude,city,country"},
                )
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("success"), bool):
                raise ValueError("Invalid geolocation response")
            if payload["success"]:
                if payload.get("ip") != canonical or any(
                    type(payload.get(field)) not in (int, float)
                    for field in ("latitude", "longitude")
                ):
                    raise ValueError("Invalid geolocation coordinates")
                result = IpLocation(
                    ip=canonical, status="located", latitude=payload["latitude"],
                    longitude=payload["longitude"], city=payload.get("city") or "",
                    country=payload.get("country") or "",
                )
            else:
                result = IpLocation(ip=canonical, status="unknown")
            self._cache[canonical] = (monotonic(), result)
            self._cache.move_to_end(canonical)
            if len(self._cache) > 1000:
                self._cache.popitem(last=False)
            return result