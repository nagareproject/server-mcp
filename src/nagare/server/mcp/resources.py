# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import io
import re
import types
from operator import itemgetter

from nagare.services.plugin import Plugin


class Resources(Plugin):
    def __init__(self, name, dist, **config):
        super().__init__(name, dist, **config)

        self.rpc_exports = {
            'list': self.list_concretes,
            'templates': {'list': self.list_templates},
            'read': self.read,
            'complete': self.complete,
        }

        self.concrete_resources = {}
        self.template_resources = []

    @property
    def entries(self):
        return [('register_resource', self.register_resource)]

    @property
    def infos(self):
        return {'subscribe': False, 'listChanged': False} if self else {}

    def register_resource(self, f, uri, name=None, mime_type='text/plain', description=None):
        regexp = re.sub('{(.+?)}', r'(?P<\1>.+?)', uri)
        if regexp == uri:
            self.concrete_resources[uri] = (f, name, mime_type, description)
        else:
            self.template_resources.append((re.compile(regexp), (f, uri, name, mime_type, description)))

    def list_concretes(self, app, channel, request_id, **params):
        resources = []

        for uri, (_, name, mime_type, description) in self.concrete_resources.items():
            resource = {'uri': uri, 'name': name}
            if description is not None:
                resource['description'] = description
            if mime_type is not None:
                resource['mimeType'] = mime_type

            resources.append(resource)

        app.send_json(channel, request_id, {'resources': resources})

    def list_templates(self, app, channel, request_id, **params):
        resources = []

        for regexp, (_, uri, name, mime_type, description) in self.template_resources:
            resource = {'uriTemplate': uri, 'name': name}
            if description is not None:
                resource['description'] = description
            if mime_type is not None:
                resource['mimeType'] = mime_type

            resources.append(resource)

        app.send_json(channel, request_id, {'resourceTemplates': resources})

    def complete(self, app, channel, request_id, argument, ref, **params):
        app.send_json(channel, request_id, {'completion': {'values': []}})

    def read(self, app, channel, request_id, uri, services_service, **params):
        f, name, mime_type, description = self.concrete_resources.get(uri, (None,) * 4)
        if f is not None:
            keywords = {}
        else:
            matching_resources = filter(
                itemgetter(0), ((reg.fullmatch(uri), params) for reg, params in self.template_resources)
            )
            match, (f, _, name, mime_type, description) = next(matching_resources, (None, (None,) * 5))
            if match is None:
                return
            keywords = match.groupdict()

        data = services_service(f, uri, name, **keywords)
        if not isinstance(data, (list, tuple, types.GeneratorType)):
            data = [data]

        streams = []
        for stream in data:
            if isinstance(stream, str):
                stream = io.StringIO(stream)
            elif isinstance(stream, bytes):
                stream = io.BytesIO(stream)

            streams.append((uri, mime_type, stream))

        app.stream_json(channel, request_id, streams)
