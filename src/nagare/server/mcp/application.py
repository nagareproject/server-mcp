# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import json
import time
import uuid
import queue
import logging
import threading
import collections
from base64 import b64encode
from functools import reduce, partial
from itertools import dropwhile

from nagare import log
from nagare.services.router import route_for
from nagare.services.plugins import Plugins
from nagare.server.http_application import RESTApp


class ClientServices:
    def __init__(self, client, progress_token, roots):
        self.client = client
        self.progress_token = progress_token
        self.roots = roots

    def progress(self, progress, total=None, message=None):
        if self.progress_token is not None:
            self.client.notify_progress(self.progress_token, progress, total, message)

    def log(self, level, data, logger=None):
        self.client.log(level, data, logger)


class Client:
    CLEANUP_PERIODICITY = 10
    LOGGING_LEVELS = {
        name: i for i, name in enumerate('debug info notice warning error critical alert emergency'.split())
    }

    def __init__(self, id, parent_logger, rpc_exports, chunk_size):
        self.id = id
        self.logger = logging.getLogger(parent_logger.name + '.client.' + self.id)
        self.chunk_size = chunk_size

        self.logging_level = self.LOGGING_LEVELS['error']
        self.roots = set()  # Roots sent by the client
        self.capabilities = {}

        self.channel = queue.Queue()
        self.request_id = 0
        self.last_message_sent = self.last_cleanup = time.time()
        self.response_callbacks = collections.OrderedDict()

        # RPC namespaces
        self.rpc_exports = rpc_exports | {
            'notifications': {
                'initialized': self.on_initialized,
                'cancelled': self.on_cancel,
                'roots': {'list_changed': self.on_roots_changed},
            },
            'ping': self.ping,
            'logging': {'setLevel': self.set_logging_level},
            'completion': {'complete': self.complete},
        }

    def cleanup(self, ping_timeout):
        now = time.time()

        if now > (self.last_message_sent + ping_timeout):
            self.send('message', json.dumps({'jsonrpc': '2.0', 'method': 'ping'}).encode('utf-8'))

        if now > (self.last_cleanup + self.CLEANUP_PERIODICITY):
            self.last_cleanup = now

            self.response_callbacks = collections.OrderedDict(
                dropwhile(
                    lambda response: (now > response[1][0] + self.CLEANUP_PERIODICITY), self.response_callbacks.items()
                )
            )

    def start_sending_loop(self, start_response, ping_timeout):
        send = start_response('200 OK', [('Content-Type', 'text/event-stream'), ('Cache-Control', 'no-cache')])

        id_ = 0  # Current SSE event IDs.
        while True:
            try:
                try:
                    # Wait for data with a timeout (for cleanup mechanism).
                    type_, data = self.channel.get(timeout=1)
                except queue.Empty:
                    self.cleanup(ping_timeout)
                    continue

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

                self.last_message_sent = time.time()
            finally:
                # If the data object has a close method (like a file stream), call it.
                getattr(data, 'close', lambda: None)()

            id_ += 1

    def send(self, data_type, data):
        if data is not None:
            self.channel.put((data_type, data))

    def __repr__(self):
        return 'Client {}'.format(self.id)

    def create_rpc_request(self, method, response_callback, **params):
        self.request_id += 1
        self.response_callbacks[self.request_id] = (time.time(), response_callback)

        return json.dumps(
            {'jsonrpc': '2.0', 'id': self.request_id, 'method': method, 'params': params},
            separators=(',', ':'),
        ).encode('utf-8')

    def create_rpc_notification(self, method, **params):
        return json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params}, separators=(',', ':')).encode('utf-8')

    @staticmethod
    def create_rpc_response(response_id, result):
        return json.dumps({'jsonrpc': '2.0', 'id': response_id, 'result': result}, separators=(',', ':')).encode(
            'utf-8'
        )

    @staticmethod
    def create_rpc_error(response_id, code, message='', data=None):
        return json.dumps(
            {
                'jsonrpc': '2.0',
                'id': response_id,
                'error': {'code': code, 'message': message} | ({'data': data} if data is not None else {}),
            },
            separators=(',', ':'),
        ).encode('utf-8')

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

    def handle_json_rpc(self, request, services_service):
        if method := request.get('method', ''):
            params = request.get('params') or {}

            self.logger.debug("Calling JSON-RPC method '%s' with %r", method, params)

            services = services_service.copy(
                client=ClientServices(self, params.get('_meta', {}).get('progressToken'), self.roots)
            )

            return services(self.invoke, method.replace('.', '/').split('/'), request.get('id'), **params)

        if error := request.get('error'):
            self.logger.error(error)

        elif 'result' in request:
            self.handle_response(**request)

        return None

    def handle_response(self, id, result, **kw):
        _, callback = self.response_callbacks.pop(id, (None, None))
        if callback is not None:
            callback(**result)

    # --- JSON-RPC Method Handlers ---

    def invoke(self, method_names, *args, services_service, **kw):
        # Follow the `rpc_exports` dictionnaries hierarchy to find the target function
        f = reduce(lambda d, name: d.get(name, {}), method_names, self.rpc_exports)

        return services_service(f, self, *args, **kw) if callable(f) else None

    def initialize(self, client_protocol_version, client_capabilities):
        self.logger.info(
            'Client protocol version: %s and capabilities: %s',
            client_protocol_version,
            ', '.join(sorted(client_capabilities)),
        )
        self.capabilities = client_capabilities

    def list_roots(self):
        return self.create_rpc_request('roots/list', self.on_roots_received)

    def on_roots_received(self, roots):
        self.logger.debug('Roots received %r', roots)
        self.roots = {(root.get('name'), root['uri']) for root in roots}

    @staticmethod
    def on_initialized(self, _):
        return self.list_roots() if 'roots' in self.capabilities else None

    @staticmethod
    def on_cancel(self, _, requestId, reason, **params):
        self.logger.debug('Cancel notification received for request: %s, reason: %s', requestId, reason)

    @staticmethod
    def on_roots_changed(self, _):
        self.list_roots()

    @staticmethod
    def set_logging_level(self, request_id, level, **params):
        self.logging_level = self.LOGGING_LEVELS[level]

        return self.create_rpc_response(request_id, {})

    @staticmethod
    def ping(self, request_id, **params):
        return self.create_rpc_response(request_id, {})

    @staticmethod
    def complete(self, *args, argument, ref, services_service, **params):
        return services_service(
            self.invoke, ((ref['type'].removeprefix('ref/')) + 's', 'complete'), *args, argument, ref, **params
        )

    def notify_progress(self, progress_token, progress, total=None, message=None):
        params = (
            {'progressToken': progress_token, 'progress': progress}
            | ({'total': total} if total is not None else {})
            | ({'message': message} if message is not None else {})
        )

        self.send('message', self.create_rpc_notification('notifications/progress', **params))

    def log(self, level, data, logger=None):
        if self.LOGGING_LEVELS[level] >= self.logging_level:
            params = {'level': level, 'data': data} | ({'logger': logger} if logger is not None else {})

            self.send('message', self.create_rpc_notification('notifications/message', **params))


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
    PROTOCOL_VERSION = '2024-11-05'

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
        self.services = services_service
        self.clients_lock = threading.Lock()
        self.clients = {}

        self.create_client = partial(
            Client,
            parent_logger=self.logger,
            rpc_exports={name: capability.rpc_exports for name, capability in self.capabilities.items()}
            | {'initialize': self.initialize},
            chunk_size=chunk_size,
        )

        for name, capability in self.capabilities.items():
            capability.name = self.name + '.' + name

    @classmethod
    def exports(cls):
        return {o.__name__: o for capability in cls.capabilities.values() for o in capability.exports()}

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

    def handle_request(self, chain, response=None, start_response=None, stdin=None, **params):
        if stdin:
            stdio_client = self.clients.get('stdio')
            if stdio_client is None:
                stdio_client = self.clients['stdio'] = self.create_client('stdio')

            response = self.services(stdio_client.handle_json_rpc, json.loads(stdin))
        else:
            response.status_code = 202
            response.start_response = start_response

            sseclient, data = super().handle_request(chain, response=response, start_response=start_response, **params)
            sseclient.send('message', data)

        return response

    def initialize(self, client, request_id, protocolVersion, capabilities, **params):
        client.initialize(protocolVersion, capabilities)

        return client.create_rpc_response(
            request_id,
            {
                'protocolVersion': self.PROTOCOL_VERSION,
                'serverInfo': {'name': self.server_name, 'version': self.version},
                'capabilities': {'roots': {}, 'completion': {}, 'logging': {}}
                | {name: capability.infos for name, capability in self.capabilities.items() if capability},
            },
        )


# --- Route Handlers ---


@route_for(MCPApp)
def create_channel(self, url, method, request, response):
    client_id = str(uuid.uuid4())
    client = self.create_client(client_id)

    with self.clients_lock:
        self.clients[client_id] = client

    log.debug('%r created', client)

    endpoint_url = request.create_redirect_url() + client_id
    client.send('endpoint', endpoint_url.encode('utf-8'))

    try:
        client.start_sending_loop(response.start_response, self.ping_timeout)
    except BrokenPipeError:
        self.logger.debug('%r disconnected', client)
    except Exception as e:
        self.logger.error('Error sending data to %r: %r', e)
        raise
    finally:
        with self.clients_lock:
            self.clients.pop(client_id, None)

    return [client, None]


@route_for(MCPApp, '{client_id:[a-f0-9-]+}', 'POST')
def handle_json_rpc(self, url, method, request, response, client_id):
    client = self.clients[client_id]

    return [client, self.services(client.handle_json_rpc, request.json_body)]
