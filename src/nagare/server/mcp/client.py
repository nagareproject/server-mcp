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
import queue
import logging
import collections
from base64 import b64encode
from functools import reduce, partial
from itertools import dropwhile

from filetype import guess_mime


class ClientServices:
    class SamplingMessage(dict):
        pass

    @classmethod
    def SamplingText(cls, text, role='user'):
        return cls.SamplingMessage(role=role, content={'type': 'text', 'text': str(text)})

    @classmethod
    def SamplingImage(cls, data, role='user', mime_type=None):
        return cls.SamplingMessage(
            role=role,
            content={
                'type': 'image',
                'mimeType': mime_type or guess_mime(data) or 'application/octet-stream',
                'data': b64encode(data).decode('ascii'),
            },
        )

    @staticmethod
    def ModelPreferences(*names, cost_priority=None, speed_priority=None, intelligence_priority=None):
        params = {
            'hints': [{'name': name} for name in names],
            'costPriority': cost_priority,
            'speedPriority': speed_priority,
            'intelligencePriority': intelligence_priority,
        }

        return {name: value for name, value in params.items() if value is not None}

    def __init__(self, client, request_id, progress_token, roots):
        self.client = client
        self.request_id = request_id
        self.progress_token = progress_token
        self.roots = roots

    def cancel(self, reason=None):
        params = {'requestId': self.request_id} | ({'reason': reason if reason is not None else {}})

        self.client.send('message', self.client.create_rpc_notification('notifications/cancelled', **params))

    def progress(self, progress, total=None, message=None):
        if self.progress_token is not None:
            params = (
                {'progressToken': self.progress_token, 'progress': progress}
                | ({'total': total} if total is not None else {})
                | ({'message': message} if message is not None else {})
            )

            self.client.send('message', self.client.create_rpc_notification('notifications/progress', **params))

    def log(self, level, data, logger=None):
        self.client.log(level, data, logger)

    def sample(
        self,
        callback,
        *messages,
        max_tokens,
        model_preferences=None,
        system_prompt=None,
        include_context=None,
        temperature=None,
        stop_sequences=None,
        metadata=None,
    ):
        params = {
            'messages': messages,
            'maxTokens': max_tokens,
            'modelPreferences': model_preferences,
            'systemPrompt': system_prompt,
            'includeContext': include_context,
            'temperature': temperature,
            'stop_sequences': stop_sequences,
            'metadata': metadata,
        }
        params = {name: value for name, value in params.items() if value is not None}

        self.client.send(
            'message',
            self.client.create_rpc_request('sampling/createMessage', callback, **params),
        )


class Client:
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

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
                client=ClientServices(self, params.get('id'), params.get('_meta', {}).get('progressToken'), self.roots)
            )

            return services(self.invoke, method.replace('.', '/'), request.get('id'), **params)

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

    def invoke(self, method, request_id, services_service, **kw):
        # Follow the `rpc_exports` dictionnaries hierarchy to find the target function
        f = reduce(lambda d, name: d.get(name, {}), method.split('/'), self.rpc_exports)

        return (
            services_service(f, self, request_id, **kw)
            if callable(f)
            else self.create_rpc_error(request_id, self.METHOD_NOT_FOUND, f'rpc method `{method}` not found')
        )

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
    def complete(self, request_id, argument, ref, services_service, **params):
        return services_service(
            self.invoke, '{}s/complete'.format(ref['type'].removeprefix('ref/')), request_id, argument=argument, ref=ref
        )

    def log(self, level, data, logger=None):
        if self.LOGGING_LEVELS[level] >= self.logging_level:
            params = {'level': level, 'data': data} | ({'logger': logger} if logger is not None else {})

            self.send('message', self.create_rpc_notification('notifications/message', **params))
