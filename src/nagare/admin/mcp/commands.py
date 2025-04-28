# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --
import json
from queue import Queue
from pprint import pprint
from threading import Thread

import httpx
import sseclient

from nagare.admin import admin


class Commands(admin.Commands):
    DESC = 'MCP subcommands'


class Command(admin.Command):
    WITH_CONFIG_FILENAME = False

    def __init__(self, name, dist, **config):
        super().__init__(name, dist, **config)
        self.endpoint = None

    @classmethod
    def _create_services(cls, *args, **kw):
        return cls.SERVICES_FACTORY()

    def set_arguments(self, parser):
        parser.add_argument('url')

        super().set_arguments(parser)

    @staticmethod
    def receive_events(url, queue):
        with httpx.stream('GET', url, headers={'Accept': 'text/event-stream'}) as stream:
            for event in sseclient.SSEClient(stream.iter_bytes()).events():
                queue.put(event)

    def start_events_listener(self, url):
        events = Queue()

        t = Thread(target=self.receive_events, args=[url, events])
        t.daemon = True
        t.start()

        event = events.get()

        if event.event == 'endpoint':
            self.endpoint = 'http://localhost:9000' + event.data

        return events

    def send(self, events, method, **params):
        data = {'jsonrpc': '2.0', 'id': 0, 'method': method, 'params': params}

        httpx.post(self.endpoint, json=data, timeout=5)
        response = events.get().data
        return json.loads(response)['result']

    def initialize(self, url):
        events = self.start_events_listener(url)
        return events, self.send(events, 'initialize')


class Info(Command):
    DESC = 'Server informations'

    def run(self, url):
        _, server_info = self.initialize(url)
        pprint(server_info)

        return 0
