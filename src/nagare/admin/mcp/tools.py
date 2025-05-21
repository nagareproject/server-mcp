# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --
from pydoc import plaintext

import yaml

from nagare.admin import admin

from .utils import create_prototype
from .commands import Command


class Tools(admin.Commands):
    DESC = 'MCP tools subcommands'


class Tool(Command):
    @staticmethod
    def bool(v):
        return v == 'true'

    CONVERTER = {'integer': int, 'boolean': bool, 'number': float, 'string': str}

    def create_tools(self):
        return {
            tool['name']: create_prototype(
                tool['name'],
                tool['description'],
                tool['inputSchema']['type'],
                [(name, prop['type']) for name, prop in tool['inputSchema']['properties'].items()],
                set(tool['inputSchema']['required']),
            )
            for tool in self.send('tools/list')['tools']
        }


class List(Tool):
    DESC = 'List the tools'

    def run(self):
        print('Available tools:\n')
        for _, proto in sorted(self.create_tools().items()):
            print(' -', plaintext.document(proto))

        return 0


class Call(Tool):
    DESC = 'Call a tool'

    def set_arguments(self, parser):
        parser.add_argument('method')
        parser.add_argument('-p', '--param', action='append', dest='params')

        super().set_arguments(parser)

    def run(self, method, params):
        tools = self.create_tools()

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

        result = self.send('tools/call', name=method.replace('.', '/'), arguments=args)
        if result['isError']:
            print('ERROR!')
        else:
            print(yaml.dump(result['content']))

        return 0
