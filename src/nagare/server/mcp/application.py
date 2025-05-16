# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import json
import uuid
import queue
import threading
from base64 import b64encode
from functools import reduce, partial

from nagare.services.router import route_for
from nagare.services.logging import log
from nagare.services.plugins import Plugins
from nagare.server.http_application import RESTApp

# Define the chunk size for streaming data.
# The size must be a multiple of 3 to ensure that base64
# encoding doesn't add padding characters ('=') within
# the stream, only potentially at the very end.
CHUNK_SIZE = 10 * 1024 + 2


class MCPApp(RESTApp):
    """Main application class for the Nagare Model Context Protocol (MCP) server.

    This class handles establishing communication channels (using Server-Sent Events),
    managing these channels, processing incoming JSON-RPC requests, and dispatching
    them to registered capabilities (plugins).
    """

    CONFIG_SPEC = RESTApp.CONFIG_SPEC | {
        'server_name': 'string(default="Nagare MCPServer")',
        'version': 'string(default=None)',
        'ping_timeout': 'integer(default=5)',
    }

    def __init__(self, name, dist, server_name, version, ping_timeout, services_service, **config):
        """Initializes the MCP application.

        Args:
            name (str): The application name.
            dist (pkg_resources.Distribution): Distribution object for the application package.
            server_name (str): Name of the MCP server.
            version (str | None): Version string for the server.
            ping_timeout (int): Timeout in seconds for the SSE ping mechanism.
            services_service (nagare.services.Services): Nagare services registry for dependency injection.
            **config: Additional configuration parameters.
        """
        services_service(
            super().__init__, name, dist, server_name=server_name, version=version, ping_timeout=ping_timeout, **config
        )
        self.server_name = server_name
        self.version = version or dist.version  # Use provided version or distribution version.
        self.ping_timeout = ping_timeout
        self.services = services_service
        self.client_capabilities = {}  # Capabilities sent by the client
        self.roots = set()  # Roots sent by the client
        self.response_handler = None

        # A lock to ensure thread-safe access to the shared `channels` dictionary.
        self.lock = threading.Lock()
        # Dictionary to store active communication channels (channel_id -> queue.Queue).
        self.channels = {}
        # Load plugins defined by the 'nagare.mcp.capabilities' entry point.
        # These plugins represent the capabilities the server offers via JSON-RPC.
        self.capabilities = Plugins().load_plugins('capabilities', entry_points='nagare.mcp.capabilities')

        # Register methods from loaded capabilities directly onto the application instance.
        # This allows calling capability methods like `self.capability_method(...)`.
        for capability in self.capabilities.values():
            for name, f in capability.entries:
                setattr(self, name, f)

        # RPC namespaces
        self.rpc_exports = {name: capability.rpc_exports for name, capability in self.capabilities.items()} | {
            'initialize': self.initialize,
            'notifications': {'initialized': self.on_initialized, 'roots': {'list_changed': self.on_roots_changed}},
            'ping': self.ping,
            'completion': {'complete': self.complete},
        }

    def handle_request(self, chain, response, start_response, **params):
        """Base request handling.

        Currently, it primarily injects the WSGI `start_response` callable into the Nagare `response`

        Args:
            chain (callable): The next middleware or handler in the request handlers chain.
            response (nagare.server.Response): The Nagare response object.
            start_response (callable): The WSGI start_response function.
            **params: Additional parameters not used in this function

        Returns:
            iterable: The response body iterable.
        """
        # Store the start_response callable in the response object for later use
        # (e.g., by the routing functions).
        response.start_response = start_response

        return super().handle_request(chain, response=response, start_response=start_response, **params)

    def create_channel(self):
        """Creates a new communication channel.

        Generates a unique channel ID and associates it with a new thread-safe queue.
        Uses a lock to ensure safe modification of the shared channels dictionary.

        Returns:
            tuple[str, queue.Queue]: The unique channel ID and the associated queue.
        """
        channel_id = str(uuid.uuid4())
        with self.lock:
            self.channels[channel_id] = channel = queue.Queue()

        return channel_id, channel

    def delete_channel(self, channel_id):
        """Removes a communication channel.

        Safely removes the channel ID and its associated queue from the dictionary.

        Args:
            channel_id (str): The ID of the channel to delete.
        """
        with self.lock:
            self.channels.pop(channel_id, None)

    def send_data(self, channel_id, data, event_type='message'):
        """Sends data to a specific channel queue.

        Args:
            channel_id (str): The ID of the target channel.
            data (bytes | iterable): The data payload to send. Can be raw bytes or an iterable (for streaming).
            event_type (str): The type of the Server-Sent Event ('message', 'endpoint', etc.).
        """
        # Put the event type and data tuple into the corresponding channel's queue.
        # This will be picked up by the `create_channel` function's event loop.
        self.channels[channel_id].put((event_type, data))

    def send_json(self, channel_id, response_id, result):
        """Sends a complete JSON-RPC response to a channel queue.

        Formats the result into a standard JSON-RPC response object and sends it.

        Args:
            channel_id (str): The ID of the target channel.
            response_id (str | int | None): The ID of the original request (or None for notifications).
            result (Any): The result payload of the JSON-RPC call.
        """
        response_data = {'jsonrpc': '2.0', 'id': response_id, 'result': result}
        self.send_data(channel_id, json.dumps(response_data).encode('utf-8'))

    @staticmethod
    def generate_iterator(response_id, streams):
        """Generates an iterator that yields parts of a JSON-RPC response for streaming multiple content streams.

        This method constructs a JSON response payload piece by piece, allowing large amounts of data
        (potentially from multiple sources like files) to be streamed to the client.

        Args:
            response_id (str | int): The ID of the original JSON-RPC request.
            streams (iterable[tuple[str, str, io.BytesIO | io.StringIO]]):
                An iterable of tuples, where each tuple represents a content stream to include
                in the response. Each tuple contains:
                - uri (str): A unique identifier.
                - mime_type (str): The MIME type of the content (e.g., 'text/plain', 'image/png').
                - stream (object): A file-like object, bytes (for binary streams) or strings (for text streams).

        Yields:
            bytes: Chunks of the JSON-RPC response string, encoded in UTF-8.
        """
        # Start the JSON-RPC response object with the beginning of the 'contents' array
        # which will hold the streamed items.
        yield b'{"jsonrpc": "2.0", "id": %s, "result": {"contents": [' % json.dumps(response_id).encode('utf-8')

        sep = b''
        for uri, mime_type, stream in streams:
            is_binary_stream = not mime_type.startswith('text/')

            yield b'%s{"uri": "%s", "mimeType": "%s", "%s": "' % (
                sep,
                uri.encode('utf-8'),
                mime_type.encode('utf-8'),
                b'blob' if is_binary_stream else b'text',
            )

            yield from (
                b64encode(chunk) if is_binary_stream else json.dumps(chunk)[1:-1].encode('utf-8')
                for chunk in iter(partial(stream.read, CHUNK_SIZE), b'' if is_binary_stream else '')
            )
            sep = b', '

            yield b'"}'

        yield b']}}'

    def stream_json(self, channel_id, response_id, streams):
        """Sends a JSON-RPC response by streaming its content using an iterator.

        This method is used when the response payload, particularly the 'result' part,
        is large or composed of multiple data streams (e.g., file contents).

        Args:
            channel_id (str): The ID of the SSE communication channel to which the
                              streamed JSON response will be sent.
            response_id (str | int): The ID of the original JSON-RPC request.
            streams (iterable[tuple[str, str, object]]):
                An iterable of tuples representing the content streams to be included
                in the JSON response. This is passed directly to `generate_iterator`.
                Each tuple contains (uri, mime_type, stream_object).
        """
        self.send_data(channel_id, self.generate_iterator(response_id, streams))

    # --- JSON-RPC Method Handlers ---

    def invoke(self, method_names, *args, services_service, **kw):
        # Follow the `rpc_exports` dictionnaries hierarchy to find the target function
        f = reduce(lambda d, name: d.get(name, {}), method_names, self.rpc_exports)
        if callable(f):
            services_service(f, self, *args, **kw)

    @staticmethod
    def initialize(self, channel_id, request_id, capabilities, **params):
        """Handles the 'initialize' JSON-RPC request from the client.

        Responds with server information and the available capabilities.

        Args:
            self (MCPApp): This application instance.
            channel_id (str): The SSE channel ID associated with the client.
            request_id (str | int): The ID of the 'initialize' request.
            capabilities: client capabilities
            **params: Any parameters sent with the initialize request (ignored).
        """
        self.client_capabilities = capabilities

        self.send_json(
            channel_id,
            request_id,
            {
                'protocolVersion': '2024-11-05',
                'serverInfo': {'name': self.server_name, 'version': self.version},
                'capabilities': {'completion': {}, 'roots': {}}
                | {name: capability.infos for name, capability in self.capabilities.items() if capability},
            },
        )

    def list_roots(self, channel_id):
        self.response_handler = self.on_roots_received
        self.send_data(channel_id, json.dumps({'jsonrpc': '2.0', 'id': 0, 'method': 'roots/list'}).encode('utf-8'))

    def on_roots_received(self, roots):
        self.roots = {root['uri'] for root in roots}

    @staticmethod
    def on_initialized(self, channel_id, _):
        if 'roots' in self.client_capabilities:
            self.list_roots(channel_id)

    @staticmethod
    def on_roots_changed(self, channel_id, _):
        self.list_roots(channel_id)

    @staticmethod
    def ping(self, channel_id, request_id, **params):
        self.send_json(channel_id, request_id, {})

    @staticmethod
    def complete(self, *args, argument, ref, services_service, **params):
        services_service(
            self.invoke, ((ref['type'].removeprefix('ref/')) + 's', 'complete'), *args, argument, ref, **params
        )


# --- Route Handlers ---


@route_for(MCPApp)
def create_channel(self, url, method, request, response):
    """Handles requests to the root URL, establishing a Server-Sent Events (SSE) connection.

    This function:
    1. Creates a new communication channel (queue).
    2. Sends the unique endpoint URL (including the channel ID) back to the client
       as the first SSE event (of 'endpoint' type). This URL is used for subsequent POST requests.
    3. Starts an SSE response stream.
    4. Enters a loop, waiting for data to appear in the channel's queue.
    5. Sends queued data (messages, responses) as SSE events to the client.
    6. Sends periodic 'ping' messages if no other data is sent within the timeout.
    7. Handles client disconnection (BrokenPipeError) and cleans up the channel.

    Args:
        self (MCPApp): The application instance.
        url (str): The request URL path
        method (str): The HTTP method ('GET').
        request (nagare.server.Request): The Nagare request object.
        response (nagare.server.Response): The Nagare response object.

    Returns:
        list: An empty list, as the true responses will be streamed
    """
    # 1. Create a new channel (ID and queue).
    channel_id, channel = self.create_channel()
    log.debug('SSE channel %s created', channel_id)

    # 2. Construct the full endpoint URL for POST requests and send it immediately.
    # This tells the client where to send subsequent JSON-RPC commands.
    endpoint_url = request.create_redirect_url() + channel_id
    self.send_data(channel_id, endpoint_url.encode('utf-8'), 'endpoint')

    # 3. Start the SSE response.
    # `send` is the WSGI callable for writing response chunks.
    send = response.start_response('200 OK', [('Content-Type', 'text/event-stream'), ('Cache-Control', 'no-cache')])

    # 4. Event loop: Continuously fetch and send data from the channel queue.
    id_ = 0  # Cuurent SSE event IDs.
    while True:
        try:
            # Wait for data with a timeout (for ping mechanism).
            type_, data = channel.get(timeout=self.ping_timeout)
        except queue.Empty:
            # 6. If timeout occurs (no data), send a ping message.
            type_ = 'message'  # Pings are sent as standard messages.
            data = json.dumps({'jsonrpc': '2.0', 'method': 'ping'}).encode('utf-8')

        # 5. Send the retrieved data (or ping) as an SSE event.
        try:
            # Format the SSE event header.
            header = b'id: %d\nevent: %s\ndata: ' % (id_, type_.encode('ascii'))

            if isinstance(data, bytes):
                # Send all the data in one go
                send(header + data + b'\n\n')
            else:
                # If data is an iterator iterate through its chunks
                send(header)
                for chunk in data:
                    send(chunk)
                send(b'\n\n')

                # If the data object has a close method (like a file stream), call it.
                getattr(data, 'close', lambda: None)()

        except BrokenPipeError:
            # 7. Client disconnected.
            log.debug('SSE channel %s disconnected', channel_id)
            self.delete_channel(channel_id)  # Clean up the channel.
            break

        except Exception as e:
            log.error('Error sending SSE data to channel %s: %s', channel_id, e)
            self.delete_channel(channel_id)  # Clean up
            raise

        id_ += 1

    return []


@route_for(MCPApp, '{channel_id:[a-f0-9-]+}', 'POST')
def handle_json_rpc(self, url, method, request, response, channel_id):
    """Handles incoming JSON-RPC requests sent via POST.

    This function:
    1. Extracts the method name, parameters, and request ID from the JSON-RPC body
    2. Determines the target function based on the method name
    3. Sends a 202 Accepted response immediately, as the actual result will be
       sent asynchronously via the SSE channel.

    Args:
        self (MCPApp): The application instance.
        url (str): The request URL path (unused).
        method (str): The HTTP method ('POST').
        request (nagare.server.Request): The Nagare request object.
        response (nagare.server.Response): The Nagare response object.
        channel_id (str): The SSE channel ID, extracted from the URL path.

    Returns:
        str: An empty response string, as the response code is set to 202.
    """
    # 1. Extract method name, parameters and ID.
    request = request.json_body

    if error := request.get('error'):
        print('ERROR FROM CLIENT', error)
    elif 'result' in request:
        self.response_handle, response_handler = None, self.response_handler
        response_handler(**request['result'])
    else:
        method = request.get('method', '')
        params = request.get('params', {})

        log.debug("JSON-RPC: Calling method '%s' with %r", method, params)

        # 2. Find the function and invoke it with dependencies injection
        self.services(self.invoke, method.replace('.', '/').split('/'), channel_id, request.get('id'), **params)

        # 3. Send '202 Accepted': Acknowledges receipt, processing happens asynchronously.
        response.status_code = 202

    return ''
