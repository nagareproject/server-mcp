# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --
from ast import Expr, Name, Return, Constant, FunctionDef, arg, unparse, arguments, fix_missing_locations
from pydoc import plaintext
from pprint import pprint

from nagare.admin import admin

from .commands import Command


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


class List(Tool):
    DESC = 'List the tools'

    def run(self, url):
        events, _ = self.initialize(url)
        tools = self.create_tools(events)

        print('Available tools:\n')
        for _, func in sorted(tools.items()):
            print(' -', plaintext.document(func))

        return 0


class Call(Tool):
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
