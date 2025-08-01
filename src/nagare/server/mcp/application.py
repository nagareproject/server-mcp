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
import threading
from functools import partial

from webob.exc import HTTPNotFound, HTTPBadRequest

from nagare import log
from nagare.services.router import route_for
from nagare.services.plugins import Plugins
from nagare.server.http_application import RESTApp

from .client import Client


class MCPApp(RESTApp):
    PROTOCOL_VERSION = '2024-11-05'

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
    CLIENTS_FACTORY = Client

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
            self.CLIENTS_FACTORY,
            parent_logger=self.logger,
            rpc_exports={name: capability.rpc_exports for name, capability in self.capabilities.items()}
            | {'initialize': self.initialize},
            chunk_size=chunk_size,
        )

        for name, capability in self.capabilities.items():
            capability.name = self.name + '.' + name

    @classmethod
    def exports(cls):
        return {o.__name__: o for capability in cls.capabilities.values() for o in capability.EXPORTS}

    @classmethod
    def decorators(cls):
        return {
            name: lambda *args, _d=decorator, _c=capability, **kw: lambda f: _d(_c, f, *args, **kw)
            for capability in cls.capabilities.values()
            for name, decorator in capability.DECORATORS
        }

    @staticmethod
    def set_response_body(_, data):
        return data

    def handle_request(self, chain, response=None, start_response=None, stdin=None, **params):
        if stdin:
            stdio_client = self.clients.get('stdio')
            if stdio_client is None:
                stdio_client = self.clients['stdio'] = self.create_client('stdio')

            try:
                payload = json.loads(stdin)
            except json.JSONDecodeError:
                self.logger.error('invalid json RPC: %s', stdin)
                response = None
            else:
                response = self.services(stdio_client.handle_json_rpc, payload)
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
                'capabilities': {'roots': {}, 'completions': {}, 'logging': {}, 'sampling': {}}
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
    client = self.clients.get(client_id)
    if client is None:
        raise HTTPNotFound()

    try:
        payload = request.json_body
    except json.JSONDecodeError:
        self.logger.error('invalid json RPC: %s', request.body)
        raise HTTPBadRequest()

    return [client, self.services(client.handle_json_rpc, payload)]
