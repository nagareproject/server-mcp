# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --
import json
import queue
import argparse
from functools import reduce
from threading import Thread

import yaml
import httpx
import sseclient

from nagare.admin import admin


class Commands(admin.Commands):
    DESC = 'MCP subcommands'


class Command(admin.Command):
    WITH_CONFIG_FILENAME = False

    def __init__(self, name, dist, **config):
        super().__init__(name, dist, **config)

        self.events = queue.Queue()
        self.endpoint = None
        self.roots = []

        self.rpc_exports = {'roots': {'list': self.list_roots}}

    @classmethod
    def _create_services(cls, *args, **kw):
        return cls.SERVICES_FACTORY()

    def set_arguments(self, parser):
        parser.add_argument('-r', '--root', nargs=2, dest='roots', action='append', metavar=('name', 'uri'))
        parser.add_argument('url')

        parser.add_argument('-_', default=self.initialize, dest='next_method', help=argparse.SUPPRESS)

        super().set_arguments(parser)

    def receive_events(self, url):
        try:
            with httpx.stream('GET', url, headers={'Accept': 'text/event-stream'}) as stream:
                for event in sseclient.SSEClient(stream.iter_bytes()).events():
                    self.events.put(event)
        except Exception as exc:
            self.events.put(exc)

    def receive_event(self):
        event = self.events.get()
        if isinstance(event, Exception):
            raise event

        if event.event != 'message':
            return event.data

        event = json.loads(event.data)
        if method := event.get('method'):
            f = reduce(lambda d, name: d.get(name, {}), method.split('/'), self.rpc_exports)
            return f(event['id']) if callable(f) else None

        return event['result']

    def start_events_listener(self, url):
        t = Thread(target=self.receive_events, args=[url])
        t.daemon = True
        t.start()

    def send_data(self, data):
        httpx.post(self.endpoint, json=data, timeout=5)

    def send(self, method, **params):
        self.send_data({'jsonrpc': '2.0', 'id': 0, 'method': method, 'params': params})
        return self.receive_event()

    def initialize(self, roots, url, **arguments):
        self.roots = roots or []

        self.start_events_listener(url)
        self.endpoint = self.receive_event()

        self.server_info = self.send('initialize', capabilities={'roots': {'listChanged': False}})
        self.send('notifications/initialized')

        return self.run(**arguments)

    def list_roots(self, request_id):
        self.send_data(
            {
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {'roots': [{'name:': name, 'uri': uri} for name, uri in self.roots]},
            }
        )


class Info(Command):
    DESC = 'Server informations'

    def run(self):
        print(yaml.dump(self.server_info, indent=4))

        return 0
