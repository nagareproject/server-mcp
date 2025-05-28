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
from nagare.services.plugins import Plugins
from nagare.server.http_application import RESTApp


class SSEClient:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.channel = queue.Queue()

    def start_sending_loop(self, start_response, ping_timeout):
        send = start_response('200 OK', [('Content-Type', 'text/event-stream'), ('Cache-Control', 'no-cache')])

        id_ = 0  # Current SSE event IDs.
        while True:
            try:
                try:
                    # Wait for data with a timeout (for ping mechanism).
                    type_, data = self.channel.get(timeout=ping_timeout)
                except queue.Empty:
                    # If timeout occurs (no data), send a ping message.
                    type_ = 'message'  # Pings are sent as standard messages.
                    data = json.dumps({'jsonrpc': '2.0', 'method': 'ping'}).encode('utf-8')

                # Send the retrieved data (or ping) as an SSE event.
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
            finally:
                # If the data object has a close method (like a file stream), call it.
                getattr(data, 'close', lambda: None)()

            id_ += 1

    def send(self, data_type, data):
        if data is not None:
            self.channel.put((data_type, data))

    def __repr__(self):
        return 'SSE client <{}>'.format(self.id)


class MCPApp(RESTApp):
    CONFIG_SPEC = RESTApp.CONFIG_SPEC | {
        'server_name': 'string(default="Nagare MCPServer")',
        'version': 'string(default=None)',
        'ping_timeout': 'integer(default=5)',
        # Define the chunk size for streaming data.
        # The size must be a multiple of 3 to ensure that base64
        # encoding doesn't add padding characters ('=') within
        # the stream, only potentially at the very end.
        'chunk_size': 'integer(default={})'.format(10 * 1024 + 2),
    }

    LOGGING_LEVELS = {
        'debug': 0,
        'info': 1,
        'notice': 2,
        'warning': 3,
        'error': 4,
        'critical': 5,
        'alert': 6,
        'emergency': 7,
    }

    capabilities = Plugins().load_plugins('capabilities', entry_points='nagare.mcp.capabilities')

    def __init__(self, name, dist, server_name, version, ping_timeout, chunk_size, services_service, **config):
        services_service(
            super().__init__,
            name,
            dist,
            server_name=server_name,
            version=version,
            ping_timeout=ping_timeout,
            chunk_size=chunk_size,
            **config,
        )

        self.server_name = server_name
        self.version = version or dist.version  # Use provided version or distribution version.
        self.ping_timeout = ping_timeout
        self.chunk_size = chunk_size
        self.services = services_service
        self.logging_level = self.LOGGING_LEVELS['error']
        self.client_capabilities = {}  # Capabilities sent by the client
        self.roots = set()  # Roots sent by the client
        self.response_handler = None

        self.sseclients_lock = threading.Lock()
        self.sseclients = {}

        # RPC namespaces
        self.rpc_exports = {name: capability.rpc_exports for name, capability in self.capabilities.items()} | {
            'initialize': self.initialize,
            'notifications': {'initialized': self.on_initialized, 'roots': {'list_changed': self.on_roots_changed}},
            'ping': self.ping,
            'logging': {'setLevel': self.set_logging_level},
            'completion': {'complete': self.complete},
        }

    @classmethod
    def decorators(cls):
        return {
            name: lambda *args, _d=decorator, _c=capability, **kw: lambda f: _d(_c, f, *args, **kw)
            for capability in cls.capabilities.values()
            for name, decorator in capability.decorators()
        }

    @staticmethod
    def set_response_body(_, data):
        return data

    @staticmethod
    def create_rpc_request(method, request_id=0, **params):
        return json.dumps(
            {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}, separators=(',', ':')
        ).encode('utf-8')

    @staticmethod
    def create_rpc_response(response_id, result):
        return json.dumps({'jsonrpc': '2.0', 'id': response_id, 'result': result}, separators=(',', ':')).encode(
            'utf-8'
        )

    def create_rpc_streaming_response(self, response_id, streams):
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
                b64encode(chunk) if is_binary_stream else json.dumps(chunk, separators=(',', ':'))[1:-1].encode('utf-8')
                for chunk in iter(partial(stream.read, self.chunk_size), b'' if is_binary_stream else '')
            )
            sep = b', '

            yield b'"}'

        yield b']}}'

    def handle_request(self, chain, response=None, start_response=None, stdin=None, **params):
        if stdin:
            response = self.handle_json_rpc('<stdio>', json.loads(stdin))
        else:
            response.status_code = 202
            response.start_response = start_response

            sseclient, data = super().handle_request(chain, response=response, start_response=start_response, **params)
            sseclient.send('message', data)

        return response

    def create_sseclient(self):
        client = SSEClient()
        with self.sseclients_lock:
            self.sseclients[client.id] = client

        return client

    def disconnect_sseclient(self, client):
        with self.sseclients_lock:
            self.sseclients.pop(client.id, None)

    def handle_json_rpc(self, client, request):
        if method := request.get('method', ''):
            params = request.get('params', {})

            self.logger.debug("Calling JSON-RPC method '%s' with %r, from %r", method, params, client)
            return self.services(self.invoke, method.replace('.', '/').split('/'), request.get('id'), **params)

        if error := request.get('error'):
            self.logger.error('From %r: %s', client, error)

        elif result := request.get('result'):
            self.response_handle, response_handler = None, self.response_handler
            response_handler(**result)

        return None

    # --- JSON-RPC Method Handlers ---

    def invoke(self, method_names, *args, services_service, **kw):
        # Follow the `rpc_exports` dictionnaries hierarchy to find the target function
        f = reduce(lambda d, name: d.get(name, {}), method_names, self.rpc_exports)

        return services_service(f, self, *args, **kw) if callable(f) else None

    @staticmethod
    def initialize(self, request_id, capabilities, **params):
        self.client_capabilities = capabilities

        return self.create_rpc_response(
            request_id,
            {
                'protocolVersion': '2024-11-05',
                'serverInfo': {'name': self.server_name, 'version': self.version},
                'capabilities': {'roots': {}, 'completion': {}, 'logging': {}}
                | {name: capability.infos for name, capability in self.capabilities.items() if capability},
            },
        )

    def list_roots(self):
        self.response_handler = self.on_roots_received
        return self.create_rpc_request('roots/list')

    def on_roots_received(self, roots):
        self.roots = {root['uri'] for root in roots}

    @staticmethod
    def on_initialized(self, _):
        return self.list_roots() if 'roots' in self.client_capabilities else None

    @staticmethod
    def on_roots_changed(self, _):
        self.list_roots()

    @staticmethod
    def set_logging_level(self, request_id, level, **params):
        self.logging_level = self.LOGGING_LEVELS[level]

        return self.create_rpc_response(request_id, {})

    """
    def send_log(self, logger, level, data):
        if self.LOGGING_LEVELS[level] >= self.logging_level:
            return self.create_rpc_request('notifications/message', leve=level, logger=logger, data=data)
    """

    @staticmethod
    def ping(self, client, request_id, **params):
        client.send_json(request_id, {})

    @staticmethod
    def complete(self, *args, argument, ref, services_service, **params):
        return services_service(
            self.invoke, ((ref['type'].removeprefix('ref/')) + 's', 'complete'), *args, argument, ref, **params
        )


# --- Route Handlers ---


@route_for(MCPApp)
def create_channel(self, url, method, request, response):
    client = self.create_sseclient()
    self.logger.debug('%r created', client)

    endpoint_url = request.create_redirect_url() + client.id
    client.send('endpoint', endpoint_url.encode('utf-8'))

    try:
        client.start_sending_loop(response.start_response, self.ping_timeout)
    except BrokenPipeError:
        self.logger.debug('%r disconnected', client)
    except Exception as e:
        self.logger.error('Error sending data to %r: %r', e)
        raise
    finally:
        self.disconnect_sseclient(client)

    return [client, None]


@route_for(MCPApp, '{client_id:[a-f0-9-]+}', 'POST')
def handle_json_rpc(self, url, method, request, response, client_id):
    client = self.sseclients[client_id]

    return [client, self.handle_json_rpc(client, request.json_body)]
