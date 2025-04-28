# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from base64 import b64encode

from nagare.services.plugin import Plugin


class Resources(Plugin, dict):
    @property
    def entries(self):
        return [('register_direct_resource', self.register_direct_resource)]

    @property
    def infos(self):
        return {'subscribe': False, 'listChanged': False} if self else {}

    def register_direct_resource(self, f, uri, name, description=None, mime_type=None):
        self[uri] = (f, name, description, mime_type)

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

        if isinstance(data, str):
            app.send_json(
                channel,
                request_id,
                {'contents': [{'uri': uri, 'mimeType': mime_type or 'text/plain', 'text': data}]},
            )
        elif isinstance(data, bytes):
            app.send_json(
                channel,
                request_id,
                {
                    'contents': [
                        {
                            'uri': uri,
                            'mimeType': mime_type or 'x-application/bytes',
                            'blob': b64encode(data).decode('ascii'),
                        },
                    ],
                },
            )
        else:
            try:
                is_binary_stream = 'b' in getattr(data, 'mode', 'b')

                app.stream_json(
                    channel,
                    request_id,
                    {
                        'contents': [
                            {
                                'uri': uri,
                                'mimeType': mime_type or ('x-application/bytes' if is_binary_stream else 'text/plain'),
                                ('blob' if is_binary_stream else 'text'): '{stream}',
                            },
                        ],
                    },
                    data,
                    is_binary_stream,
                )
            finally:
                getattr(data, 'close', lambda: None)()
