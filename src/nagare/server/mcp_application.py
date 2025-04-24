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

import requests
from webob.exc import HTTPOk

from nagare.services.router import route_for
from nagare.services.logging import log
from nagare.server.http_application import RESTApp


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

        self.tools = {}

    def send_data(self, channel, content_type, event_type, data):
        requests.post(
            self.send_url.format(channel),
            headers={'Content-type': content_type, 'X-EventSource-Event': event_type},
            data=data,
            timeout=self.timeout,
        )

    def send_json(self, channel, response_id, result):
        self.send_data(
            channel,
            'application/json-rpc',
            'message',
            json.dumps({'jsonrpc': '2.0', 'id': response_id, 'result': result}),
        )

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

    def initialize_rpc(self, **params):
        return {
            'protocolVersion': '2024-11-05',
            'serverInfo': {'name': self.server_name, 'version': self.version},
            'capabilities': {
                'tools': {'listChanged': False},
            },
        }

    def tools__list_rpc(self, **params):
        return {'tools': [{'name': name} | meta for name, (_, meta) in sorted(self.tools.items())]}

    def tools__call_rpc(self, name, arguments, **params):
        log.debug("Calling tool '%s' with %r", name, arguments)

        f = self.tools[name][0]
        r = f(**arguments)

        return {'isError': False, 'content': [{'type': 'text', 'text': str(r)}]}


@route_for(MCPApp, '/sse')
def create_channel(self, url, method, request, response):
    raise HTTPOk(headers={'X-Accel-Redirect': '/sub/{}'.format(uuid.uuid4()), 'X-Accel-Buffering': 'no'})


@route_for(MCPApp, '/_sub/{channel:[a-f0-9-]+}')
def subscribe(self, url, method, request, response, channel):
    self.send_data(channel, 'text/plain', 'endpoint', self.receive_url.format(channel))


@route_for(MCPApp, '/rpc/{channel:[a-f0-9-]+}', 'POST')
def route(self, url, method, request, response, channel):
    request = request.json_body
    method = request['method']
    params = request.get('params', {})

    log.debug("JSON-RPC: Calling method '%s' with %r", method, params)

    f = getattr(self, method.replace('.', '__').replace('/', '__') + '_rpc', None)

    if f is not None:
        self.send_json(channel, request['id'], f(**params))

    response.status_code = 202
    return ''
