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
from base64 import b64encode
from functools import partial
from itertools import chain

import httpx
from webob.exc import HTTPOk

from nagare.services.router import route_for
from nagare.services.logging import log
from nagare.services.plugins import Plugins
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

    def __init__(self, name, dist, server_name, version, receive_url, send_url, timeout, services_service, **config):
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
        self.services = services_service

        self.capabilities = Plugins().load_plugins('capabilities', entry_points='nagare.mcp.capabilities')

        for capability in self.capabilities.values():
            for name, f in capability.entries:
                setattr(self, name, f)

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

    # ---

    @staticmethod
    def initialize_rpc(self, channel, request_id, **params):
        capabilities = {}

        for name, capability in self.capabilities.items():
            infos = capability.infos
            if infos:
                capabilities[name] = infos

        self.send_json(
            channel,
            request_id,
            {
                'protocolVersion': '2024-11-05',
                'serverInfo': {'name': self.server_name, 'version': self.version},
                'capabilities': capabilities,
            },
        )


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

    tool, _, method = (method.replace('.', '/') + '_rpc').partition('/')
    f = getattr(self.capabilities[tool], method, None) if method else getattr(self, tool, None)
    if f is not None:
        self.services(f, self, channel, request['id'], **params)

    response.status_code = 202
    return ''
