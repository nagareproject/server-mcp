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
from functools import partial
from itertools import chain

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

        self.lock = threading.Lock()
        self.channels = {}
        self.capabilities = Plugins().load_plugins('capabilities', entry_points='nagare.mcp.capabilities')

        for capability in self.capabilities.values():
            for name, f in capability.entries:
                setattr(self, name, f)

    def handle_request(self, chain, response, start_response, **params):
        response.start_response = start_response

        return super().handle_request(chain, response=response, start_response=start_response, **params)

    def create_channel(self):
        channel_id = str(uuid.uuid4())
        with self.lock:
            self.channels[channel_id] = channel = queue.Queue()

        return channel_id, channel

    def delete_channel(self, channel_id):
        with self.lock:
            self.channels.pop(channel_id, None)

    def send_data(self, channel, data, event_type='message'):
        self.channels[channel].put((event_type, data))

    def send_json(self, channel, response_id, result):
        self.send_data(channel, [json.dumps({'jsonrpc': '2.0', 'id': response_id, 'result': result}).encode('utf-8')])

    def stream_json(self, channel, response_id, result, stream, binary_stream=False):
        json_prefix, json_suffix = json.dumps({'jsonrpc': '2.0', 'id': response_id, 'result': result}).split('{stream}')

        self.send_data(
            channel,
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


@route_for(MCPApp)
def create_channel(self, url, method, request, response):
    channel_id, channel = self.create_channel()

    self.send_data(channel_id, [(request.create_redirect_url() + channel_id).encode('utf-8')], 'endpoint')

    send = response.start_response('200 Ok', [('Content-Type', 'text/event-stream'), ('Cache-Control', 'no-cache')])

    id_ = 0
    while True:
        try:
            type_, data = channel.get(timeout=2)
        except queue.Empty:
            type_ = 'message'
            data = [json.dumps({'jsonrpc': '2.0', 'id': str(id_), 'method': 'ping'}).encode('utf-8')]

        try:
            send(f'id: {id_}\nevent: {type_}\ndata: '.encode('utf-8'))
            for chunk in data:
                send(chunk)
            send(b'\n\n')

            getattr(data, 'close', lambda: None)()
        except Exception:
            self.delete_channel(channel_id)
            break

        id_ += 1

    return []


@route_for(MCPApp, '{channel:[a-f0-9-]+}', 'POST')
def handle_json_rpc(self, url, method, request, response, channel):
    request = request.json_body
    method = request.get('method', '')
    params = request.get('params', {})

    log.debug("JSON-RPC: Calling method '%s' with %r", method, params)

    tool, _, method = (method.replace('.', '/') + '_rpc').partition('/')
    f = getattr(self.capabilities.get(tool), method, None) if method else getattr(self, tool, None)
    if f is not None:
        self.services(f, self, channel, request['id'], **params)

    response.status_code = 202
    return ''
