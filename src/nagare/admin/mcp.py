# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --
import sys
import json
from ast import Expr, Name, Return, Constant, FunctionDef, arg, unparse, arguments, fix_missing_locations
from pydoc import plaintext
from queue import Queue
from base64 import b64decode
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


class Resources(admin.Commands):
    DESC = 'MCP resources subcommands'


class ResourcesList(Command):
    DESC = 'List the resources'

    def run(self, url):
        events, _ = self.initialize(url)

        print('Available resources:\n')
        for resource in self.send(events, 'resources/list')['resources']:
            print(
                ' -',
                resource['uri'],
                resource['name'],
                resource.get('mimeType', ''),
                resource.get('description', ''),
            )

        return 0


class ResourcesDescribe(Command):
    DESC = 'Describe a resource'

    def set_arguments(self, parser):
        parser.add_argument('-n', default=0)
        parser.add_argument('uri')

        super().set_arguments(parser)

    def run(self, url, uri, n):
        events, _ = self.initialize(url)

        content = self.send(events, 'resources/read', uri=uri)['contents'][n]
        blob = content.pop('blob', None)
        data = b64decode(blob) if blob is not None else content['text']
        content.pop('text', None)

        pprint(content | {'length': len(data)})

        return 0


class ResourcesRead(Command):
    DESC = 'Fetch a resource'

    def set_arguments(self, parser):
        parser.add_argument('-n', default=0)
        parser.add_argument('uri')

        super().set_arguments(parser)

    def run(self, url, uri, n):
        events, _ = self.initialize(url)

        content = self.send(events, 'resources/read', uri=uri)['contents'][n]
        blob = content.get('blob')
        if blob is not None:
            sys.stdout.buffer.write(b64decode(blob))
        else:
            print(content['text'])

        return 0


class Tools(admin.Commands):
    DESC = 'MCP tools subcommands'


class Tool(Command):
    @staticmethod
    def bool(v):
        return v == 'true'

    CONVERTER = {'integer': int, 'boolean': bool, 'number': float, 'string': str}

    def create_prototype(self, name, description, return_type, params, required):
        func = FunctionDef(
            name,
            arguments(
                kwonlyargs=[arg(name, annotation=Name(self.CONVERTER[type_].__name__)) for name, type_ in params],
                kw_defaults=[None if name in required else Constant(None) for name, _ in params],
            ),
            [
                Expr(Constant(description)),
                Return(Constant(None)),
            ],
        )

        globals_ = {}
        exec(unparse(fix_missing_locations(func)), globals_)  # noqa: S102

        return globals_[name]

    def create_tools(self, events):
        return {
            tool['name']: self.create_prototype(
                tool['name'],
                tool['inputSchema']['title'],
                tool['inputSchema']['type'],
                [(name, prop['type']) for name, prop in tool['inputSchema']['properties'].items()],
                set(tool['inputSchema']['required']),
            )
            for tool in self.send(events, 'tools/list')['tools']
        }


class ToolsList(Tool):
    DESC = 'List the tools'

    def run(self, url):
        events, _ = self.initialize(url)
        tools = self.create_tools(events)

        print('Available tools:\n')
        for _, func in sorted(tools.items()):
            print(' -', plaintext.document(func))

        return 0


class ToolsCall(Tool):
    DESC = 'Call a tool'

    def set_arguments(self, parser):
        parser.add_argument('method')
        parser.add_argument('-p', '--param', action='append', dest='params')

        super().set_arguments(parser)

    def run(self, url, method, params):
        events, _ = self.initialize(url)
        tools = self.create_tools(events)

        func = tools.get(method)
        if func is None:
            print('Error: tool not found!')
            return -1

        try:
            args = {}
            for param in params or ():
                name, value = param.split('=')
                args[name] = func.__annotations__.get(name, lambda v: v)(value)

            func(**args)
        except Exception as e:
            print('Error:', e)
            return -1

        result = self.send(events, 'tools/call', name=method.replace('.', '/'), arguments=args)
        if result['isError']:
            print('ERROR!')
        else:
            pprint(result['content'])

        return 0
