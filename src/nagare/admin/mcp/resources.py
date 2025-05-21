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


class Describe(Command):
    DESC = 'Describe a resource'

    def set_arguments(self, parser):
        parser.add_argument('-n', type=int, default=1)
        parser.add_argument('uri')

        super().set_arguments(parser)

    def run(self, uri, n):
        contents = self.send('resources/read', uri=uri)['contents']
        content = contents[n - 1]
        blob = content.pop('blob', None)
        data = b64decode(blob) if blob is not None else content['text']
        content.pop('text', None)

        print(yaml.dump(content | {'contents': len(contents), 'length': len(data)}))

        return 0


class Read(Command):
    DESC = 'Fetch a resource'

    def set_arguments(self, parser):
        parser.add_argument('-n', type=int, default=0)
        parser.add_argument('uri')

        super().set_arguments(parser)

    def run(self, uri, n):
        content = self.send('resources/read', uri=uri)['contents'][n - 1]
        blob = content.get('blob')
        if blob is not None:
            sys.stdout.buffer.write(b64decode(blob))
        else:
            print(content['text'])

        return 0
