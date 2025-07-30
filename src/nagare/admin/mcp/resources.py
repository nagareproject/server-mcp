# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import sys
from base64 import b64decode

import yaml

from nagare.admin import admin

from .commands import Command


class Resources(admin.Commands):
    DESC = 'MCP resources subcommands'


class List(Command):
    DESC = 'List the resources'

    def run(self):
        print('Available resources:\n')
        for resource in self.send('resources/list')['resources']:
            print(
                ' -',
                resource['uri'],
                resource['name'],
                resource.get('mimeType', ''),
                resource.get('description', ''),
            )

        return 0


class Templates(admin.Commands):
    DESC = 'MCP resources templates subcommands'


class TemplatesList(Command):
    DESC = 'List the template resources'

    def run(self):
        print('Available template resources:\n')
        for resource in self.send('resources/templates/list')['resourceTemplates']:
            print(
                ' -',
                resource['uriTemplate'],
                resource['name'],
                resource.get('mimeType', ''),
                resource.get('description', ''),
            )

        return 0


class Read(Command):
    DESC = 'Fetch a resource'

    def set_arguments(self, parser):
        parser.add_argument('-n', type=int, default=None, help='display a specific content')
        parser.add_argument('uri')

        super().set_arguments(parser)

    def run(self, uri, n):
        result = self.send('resources/read', uri=uri)

        if (code := result.get('code')) is not None:
            print('Error:', result.get('message', code))
            return -1

        contents = result.get('contents', ())

        if n:
            if (nb := len(contents)) < n:
                print(f'Error: only {nb} contents available')
                return -1

            content = contents[n - 1]

            if blob := content.get('blob'):
                sys.stdout.buffer.write(b64decode(blob))
            else:
                print(content['text'])
        else:
            print(yaml.dump([content | ({'blob': '...'} if 'blob' in content else {}) for content in contents]))

        return 0
