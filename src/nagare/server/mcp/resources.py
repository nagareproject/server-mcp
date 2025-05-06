# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import io
import types

from nagare.services.plugin import Plugin


class Resources(Plugin, dict):
    @property
    def entries(self):
        return [('register_direct_resource', self.register_direct_resource)]

    @property
    def infos(self):
        return {'subscribe': False, 'listChanged': False} if self else {}

    def register_direct_resource(self, f, uri, name=None, mime_type='text/plain', description=None):
        self[uri] = (f, name or uri, description, mime_type)

    def list_rpc(self, app, channel, request_id, **params):
        resources = []

        for uri, (_, name, description, mime_type) in sorted(self.items()):
            resource = {'uri': uri, 'name': name}
            if description is not None:
                resource['description'] = description
            if mime_type is not None:
                resource['mimeType'] = mime_type

            resources.append(resource)

        app.send_json(channel, request_id, {'resources': resources})

    def read_rpc(self, app, channel, request_id, uri, services_service, **params):
        f, name, description, mime_type = self[uri]
        data = services_service(f, uri, name)

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
