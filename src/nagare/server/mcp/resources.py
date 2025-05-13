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


class Resources(Plugin, list):
    @property
    def entries(self):
        return [('register_resource', self.register_resource)]

    @property
    def infos(self):
        return {'subscribe': False, 'listChanged': False} if self else {}

    def register_resource(self, f, uri, name=None, mime_type='text/plain', description=None):
        self.append((re.compile(re.sub('{(.+?)}', r'(?P<\1>.+?)', uri)), (f, uri, name, mime_type, description)))

    def list_rpc(self, app, channel, request_id, **params):
        resources = []

        for reg, (_, uri, name, mime_type, description) in self:
            resource = {'uri': uri, 'name': name}
            if description is not None:
                resource['description'] = description
            if mime_type is not None:
                resource['mimeType'] = mime_type

            resources.append(resource)

        app.send_json(channel, request_id, {'resources': resources})

    def read_rpc(self, app, channel, request_id, uri, services_service, **params):
        matching_resources = filter(itemgetter(0), ((reg.fullmatch(uri), params) for reg, params in self))
        match, (f, _, name, mime_type, description) = next(matching_resources, (None, (None,) * 5))
        if match is None:
            return

        data = services_service(f, uri, name, **match.groupdict())
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
