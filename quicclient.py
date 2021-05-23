"""
This module contains the QUIC request stuff.

Adapted from https://github.com/aiortc/aioquic/blob/3d2708013aa959d70b7e4dbcd6cfb173c5ac4359/examples/http3_client.py
"""

import asyncio
import collections
import time
import logging
from urllib.parse import urlparse

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import (
    DataReceived,
    HeadersReceived,
)
from aioquic.quic.events import ConnectionTerminated
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio.client import connect

logger = logging.getLogger("client")
logger.setLevel(logging.INFO)
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.97 Safari/537.36"
HTTPRequest = collections.namedtuple("HTTPRequest", ["content", "headers", "method", "url"])


class InvidiousRequest:
    def __init__(self, url, method, headers, content):
        self.url = urlparse(url)
        self.method = method
        self.headers = headers
        self.content = content

        self.completed = asyncio.Event()


class URL:
    def __init__(self, url):
        self.authority = url.netloc
        self.full_path = url.path
        if url.query:
            self.full_path += "?" + url.query
        self.scheme = url.scheme


class HttpClient(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._http = H3Connection(self._quic)
        self._request_events = {}
        self._request_waiter = {}

        self.terminated = False

    async def get(self, url, headers=None):
        """
        Perform a GET request.
        """
        headers = {} if not headers else headers

        return await self._request(
            HTTPRequest(method="GET", url=URL(url), headers=headers, content=b"")
        )

    async def post(self, url: str, data: bytes, headers=None):
        """
        Perform a POST request.
        """
        headers = {} if not headers else headers

        return await self._request(
            HTTPRequest(method="POST", url=URL(url), content=data, headers=headers)
        )

    def http_event_received(self, event):
        if isinstance(event, (HeadersReceived, DataReceived)):
            stream_id = event.stream_id
            if stream_id in self._request_events:
                # http
                self._request_events[event.stream_id].append(event)
                if event.stream_ended:
                    request_waiter = self._request_waiter.pop(stream_id)
                    request_waiter.set_result(self._request_events.pop(stream_id))

    def quic_event_received(self, event):
        if isinstance(event, ConnectionTerminated):
            self.terminated = True

        #  pass event to the HTTP layer
        for http_event in self._http.handle_event(event):
            self.http_event_received(http_event)

    async def _request(self, http_request):
        stream_id = self._quic.get_next_available_stream_id()
        headers = await self.fetch_default_headers(http_request)

        # Custom headers
        for k, v in http_request.headers.items():
            headers[k.encode()] = v.encode()

        self._http.send_headers(
            stream_id=stream_id,
            headers=[(k, v) for k, v in headers.items()],
        )
        self._http.send_data(stream_id=stream_id, data=http_request.content, end_stream=True)

        waiter = self._loop.create_future()
        self._request_events[stream_id] = collections.deque()
        self._request_waiter[stream_id] = waiter
        self.transmit()

        return await asyncio.shield(waiter)

    async def fetch_default_headers(self, http_request):
        return {b":method": http_request.method.encode(),
                b":scheme": http_request.url.scheme.encode(),
                b":authority": http_request.url.authority.encode(),
                b":path": http_request.url.full_path.encode() or b"/",
                b"user-agent": USER_AGENT.encode()}


async def perform_http_request(client, url, method, headers, data, store_at):
    # perform request
    start = time.time()

    if method == "POST":
        http_events = await client.post(url, data.encode(), headers=headers)
    else:
        http_events = await client.get(url, headers=headers)
    elapsed = time.time() - start

    # log speed
    octets = 0
    for http_event in http_events:
        if isinstance(http_event, DataReceived):
            octets += len(http_event.data)
    logger.info(
        "Response received for %s %s : %d bytes in %.1f s (%.3f Mbps)"
        % (method, url.path, octets, elapsed, octets * 8 / elapsed / 1000000)
    )
    s = time.time()
    await handle_response(http_events, store_at)
    e = time.time() - s

    logger.info(
        "Response has been stored in %.1f s)"
        % elapsed
    )


async def handle_response(http_events, store_at=None):
    resulting_data = {}
    _accumulator = b""

    for http_event in http_events:
        if isinstance(http_event, HeadersReceived):
            headers = {}
            for k, v in http_event.headers:
                headers[k.decode()] = v.decode()
            resulting_data["headers"] = headers

        elif isinstance(http_event, DataReceived):
            if not http_event.stream_ended:
                _accumulator += http_event.data
                continue
            _accumulator += http_event.data

            # If a content type header isn't available then we don't have a response to get.
            if not resulting_data["headers"].get("content-type"):
                return

            if resulting_data["headers"]["content-type"].startswith("image"):
                resulting_data["response"] = _accumulator
            else:
                resulting_data["response"] = _accumulator.decode()

    if store_at is not None:
        store_at.update(resulting_data)
        return store_at


class RequestProcessor:
    def __init__(self):
        # {InvidiousRequest, storage_dict}
        self.requests_to_do = asyncio.Queue(0)
        self.paused_requests = asyncio.Queue(0)
        self.processors = []

    async def request_worker(self):
        configuration = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)

        while self.recreate_connection_check():
            async with connect("youtube.com", 443, configuration=configuration, create_protocol=HttpClient) as client:
                while True:
                    status = await self._handle_request(client)
                    # Connection has been terminated.
                    if status is False:
                        break

    async def _handle_request(self, client):
        # Paused requests has a higher priority than the normal staged requests.
        try:
            request, storage = self.paused_requests.get_nowait()
        except asyncio.QueueEmpty:
            request, storage = await self.requests_to_do.get()

        if client.terminated:
            # Client has to be recreated so we'll put the current request on pause.
            await self.paused_requests.put([request, storage])
            return False

        await perform_http_request(client=client, url=request.url, method=request.method,
                                   headers=request.headers, data=request.content,
                                   store_at=storage)

        request.completed.set()

    def recreate_connection_check(self):
        # TODO in the future this code should calculate whether or not to recreate a connection based on the amount
        #  of connections currently available and the amount of traffic we're currently receiving. For now we'll
        # just have it recreate a connection anytime it's broken.
        return True
