# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --
import json
from ast import Lambda, Constant, Expression, arg, unparse, arguments
from pydoc import plaintext
from queue import Queue
from pprint import pprint
from threading import Thread

import requests
import requests_sse

from nagare.admin import admin


class EventSource(requests_sse.EventSource):
    def connect(self, retry):
        super().connect(retry)
        self._data_generator = self._response.iter_lines(1)


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
    def receive(url, queue):
        with EventSource(url) as events:
            for event in events:
                queue.put(event)

    def start_sse(self, url):
        events = Queue()

        t = Thread(target=self.receive, args=[url, events])
        t.daemon = True
        t.start()

        event = events.get()

        if event.type == 'endpoint':
            self.endpoint = 'http://localhost:9000' + event.data

        return events

    def send(self, events, method, **params):
        data = {'jsonrpc': '2.0', 'id': 0, 'method': method, 'params': params}

        requests.post(self.endpoint, data=json.dumps(data), timeout=5)
        response = events.get().data
        return json.loads(response)['result']

    def initialize(self, url):
        events = self.start_sse(url)
        return events, self.send(events, 'initialize')


class Info(Command):
    DESC = 'Server informations'

    def run(self, url):
        _, server_info = self.initialize(url)
        pprint(server_info)

        return 0


class Tools(admin.Commands):
    DESC = 'MCP tools subcommands'


class Tool(Command):
    class bool(int):
        __qualname__ = 'bool'
        __module__ = 'builtins'

        def __new__(self, v):
            return super().__new__(self, v == 'true')

    CONVERTER = {'integer': int, 'boolean': bool, 'number': float, 'string': str}

    def create_prototype(self, name, description, return_type, params, required):
        func = eval(  # noqa: S307
            unparse(
                Expression(
                    Lambda(
                        arguments(
                            kwonlyargs=[arg(name) for name, _ in params],
                            kw_defaults=[None if name in required else Constant(None) for name, _ in params],
                        ),
                        Constant(None),
                    )
                )
            )
        )

        func.__name__ = func.__qualname__ = name
        func.__doc__ = description
        func.__annotations__ = {
            name: self.CONVERTER[type_] for name, type_ in params + [('return', return_type)] if type_ != 'object'
        }

        return func

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
