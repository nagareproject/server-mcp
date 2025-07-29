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
from nagare.server.mcp.prototypes import jsonschema_to_proto

from .commands import Command


class Tools(admin.Commands):
    DESC = 'MCP tools subcommands'


class Tool(Command):
    def create_tools(self):
        return {tool['name']: tool for tool in self.send('tools/list')['tools']}


class List(Tool):
    DESC = 'List the tools'

    def run(self):
        print('Available tools:\n')
        for _, schema in sorted(self.create_tools().items()):
            print(' -', plaintext.document(jsonschema_to_proto(schema)))

        return 0


class Call(Tool):
    DESC = 'Call a tool'

    def set_arguments(self, parser):
        parser.add_argument('method')
        parser.add_argument('-p', '--param', action='append', dest='params')

        super().set_arguments(parser)

    def run(self, method, params):
        tools = self.create_tools()

        schema = tools.get(method)
        if schema is None:
            print('Error: tool not found!')
            return -1

        proto = jsonschema_to_proto(schema)

        try:
            args = {}
            for param in params or ():
                name, value = param.split('=')
                args[name] = proto.__annotations__.get(name, lambda v: v)(value)

            proto(**args)
        except Exception as e:
            print('Protocol Error:', e)
            return -1

        result = self.send('tools/call', name=method.replace('.', '/'), arguments=args)

        if 'code' in result:
            print('Protocol Error:', result.get('message') or result['code'])
        elif result.pop('isError', False):
            print('Call Error:', result['content'][0]['text'])
        else:
            print(yaml.dump(result))

        return 0
