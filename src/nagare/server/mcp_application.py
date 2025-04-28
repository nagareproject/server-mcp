# Encoding: utf-8

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
import inspect
from base64 import b64encode
from functools import partial
from itertools import chain

import httpx
from webob.exc import HTTPOk

from nagare.services.router import route_for
from nagare.services.logging import log
from nagare.server.http_application import RESTApp

CHUNK_SIZE = 10 * 1024 + 2  # Must a multiple of 3 (for base64 encoding)


class MCPApp(RESTApp):
    CONFIG_SPEC = RESTApp.CONFIG_SPEC | {
        'server_name': 'string(default="Nagare MCPServer")',
        'version': 'string(default=None)',
        'receive_url': 'string(default="/rpc/{}")',
        'send_url': 'string(default="http://127.0.0.1:9001/pub/{}")',
        'timeout': 'integer(default=5)',
    }

    CONVERTER = {inspect.Parameter.empty: 'object', int: 'integer', bool: 'boolean', float: 'number', str: 'string'}

    def __init__(self, name, dist, services_service, server_name, version, receive_url, send_url, timeout, **config):
        services_service(
            super().__init__,
            name,
            dist,
            server_name=server_name,
            version=version,
            receive_url=receive_url,
            send_url=send_url,
            timeout=timeout,
            **config,
        )

        self.server_name = server_name
        self.version = version or dist.version
        self.receive_url = receive_url
        self.send_url = send_url
        self.timeout = timeout

        self.direct_resources = {}
        self.tools = {}

    def send_data(self, channel, content_type, event_type, data):
        httpx.post(
            self.send_url.format(channel),
            headers={'Content-type': content_type, 'charset': 'utf-8', 'X-EventSource-Event': event_type},
            content=data,
            timeout=self.timeout,
        )

    def _send_json(self, channel, response_id, json_data):
        self.send_data(channel, 'application/json-rpc', 'message', json_data)

    def send_json(self, channel, response_id, result):
        self._send_json(channel, response_id, json.dumps({'jsonrpc': '2.0', 'id': response_id, 'result': result}))

    def stream_json(self, channel, response_id, result, stream, binary_stream=False):
        json_prefix, json_suffix = json.dumps({'jsonrpc': '2.0', 'id': response_id, 'result': result}).split('{stream}')

        self._send_json(
            channel,
            response_id,
            chain(
                [json_prefix.encode('utf-8')],
                map(b64encode, iter(partial(stream.read, CHUNK_SIZE), b''))
                if binary_stream
                else (json.dumps(chunk)[1:-1].encode('utf-8') for chunk in iter(partial(stream.read, CHUNK_SIZE), '')),
                [json_suffix.encode('utf8')],
            ),
        )

    def register_direct_resource(self, f, uri, name, description=None, mime_type=None):
        self.direct_resources[uri] = (f, name, description, mime_type)

    def register_tool(self, f, func_name=None):
        sig = inspect.signature(f)

        params = {}
        required = set()
        for name, param in sig.parameters.items():
            if name != 'self':
                has_default = param.default is not inspect.Parameter.empty
                if not has_default:
                    required.add(name)

                params[name] = {'type': self.CONVERTER[param.annotation]}
                if has_default:
                    params[name]['default'] = param.default

        self.tools[func_name or f.__name__] = (
            f,
            {
                'description': f.__doc__ or '',
                'inputSchema': {
                    'properties': params,
                    'required': tuple(required),
                    'title': f.__doc__ or '',
                    'type': self.CONVERTER[sig.return_annotation],
                },
            },
        )

    # ---

    def initialize_rpc(self, channel, request_id, **params):
        capabilities = {}
        if self.direct_resources:
            capabilities['resources'] = {'subscribe': False, 'listChanged': False}

        if self.tools:
            capabilities['tools'] = {'listChanged': False}

        self.send_json(
            channel,
            request_id,
            {
                'protocolVersion': '2024-11-05',
                'serverInfo': {'name': self.server_name, 'version': self.version},
                'capabilities': capabilities,
            },
        )

    def resources__list_rpc(self, channel, request_id, **params):
        resources = []

        for uri, (_, name, description, mime_type) in sorted(self.direct_resources.items()):
            resource = {'uri': uri, 'name': name}
            if description is not None:
                resource['description'] = description
            if mime_type is not None:
                resource['mimeType'] = mime_type

            resources.append(resource)

        self.send_json(channel, request_id, {'resources': resources})

    def resources__read_rpc(self, channel, request_id, uri, **params):
        f, name, description, mime_type = self.direct_resources[uri]
        data = f(uri, name)

        if isinstance(data, str):
            self.send_json(
                channel,
                request_id,
                {'contents': [{'uri': uri, 'mimeType': mime_type or 'text/plain', 'text': data}]},
            )
        elif isinstance(data, bytes):
            self.send_json(
                channel,
                request_id,
                {
                    'contents': [
                        {
                            'uri': uri,
                            'mimeType': mime_type or 'x-application/bytes',
                            'blob': b64encode(data).decode('ascii'),
                        },
                    ],
                },
            )
        else:
            try:
                is_binary_stream = 'b' in getattr(data, 'mode', 'b')

                self.stream_json(
                    channel,
                    request_id,
                    {
                        'contents': [
                            {
                                'uri': uri,
                                'mimeType': mime_type or ('x-application/bytes' if is_binary_stream else 'text/plain'),
                                ('blob' if is_binary_stream else 'text'): '{stream}',
                            },
                        ],
                    },
                    data,
                    is_binary_stream,
                )
            finally:
                getattr(data, 'close', lambda: None)()

    def tools__list_rpc(self, channel, request_id, **params):
        self.send_json(
            channel,
            request_id,
            {'tools': [{'name': name} | meta for name, (_, meta) in sorted(self.tools.items())]},
        )

    def tools__call_rpc(self, channel, request_id, name, arguments, **params):
        log.debug("Calling tool '%s' with %r", name, arguments)

        f = self.tools[name][0]
        r = f(**arguments)

        self.send_json(channel, request_id, {'isError': False, 'content': [{'type': 'text', 'text': str(r)}]})


@route_for(MCPApp, '/sse')
def create_channel(self, url, method, request, response):
    raise HTTPOk(headers={'X-Accel-Redirect': '/sub/{}'.format(uuid.uuid4()), 'X-Accel-Buffering': 'no'})


@route_for(MCPApp, '/_sub/{channel:[a-f0-9-]+}')
def subscribe(self, url, method, request, response, channel):
    self.send_data(channel, 'text/plain', 'endpoint', self.receive_url.format(channel))


@route_for(MCPApp, '/rpc/{channel:[a-f0-9-]+}', 'POST')
def handle_json_rpc(self, url, method, request, response, channel):
    request = request.json_body
    method = request['method']
    params = request.get('params', {})

    log.debug("JSON-RPC: Calling method '%s' with %r", method, params)

    f = getattr(self, method.replace('.', '__').replace('/', '__') + '_rpc', None)
    if f is not None:
        f(channel, request['id'], **params)

    response.status_code = 202
    return ''
