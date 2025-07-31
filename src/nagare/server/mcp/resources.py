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
import inspect

from nagare.services.plugin import Plugin


class Resources(Plugin):
    PLUGIN_CATEGORY = 'nagare.applications'

    def __init__(self, name, dist, **config):
        super().__init__(name, dist, **config)

        self.concrete_resources = {}
        self.template_resources = {}

    @property
    def rpc_exports(self):
        return {
            'list': self.list_concretes,
            'templates': {'list': self.list_templates},
            'read': self.read,
            'complete': self.complete,
        }

    @property
    def infos(self):
        return {'subscribe': False, 'listChanged': False} if self else {}

    def register(self, f, uri=None, name=None, mime_type='text/plain', description=None, completions=None):
        name = name or f.__name__
        uri = uri or name
        description = description or inspect.cleandoc(f.__doc__ or '')

        regexp = re.sub('{(.+?)}', r'(?P<\1>.+?)', uri)
        if regexp == uri:
            self.concrete_resources[uri] = (f, name, mime_type, description)
        else:
            self.template_resources[uri] = (re.compile(regexp), f, name, mime_type, description, completions or {})

        return f

    def list_concretes(self, client, request_id, **params):
        resources = [
            {'uri': uri, 'name': name}
            | ({'description': description} if description is not None else {})
            | ({'mimeType': mime_type} if mime_type is not None else {})
            for uri, (_, name, mime_type, description) in self.concrete_resources.items()
        ]

        return client.create_rpc_response(request_id, {'resources': resources})

    def list_templates(self, client, request_id, **params):
        resources = [
            {'uriTemplate': uri, 'name': name}
            | ({'description': description} if description is not None else {})
            | ({'mimeType': mime_type} if mime_type is not None else {})
            for uri, (_, _, name, mime_type, description, _) in self.template_resources.items()
        ]

        return client.create_rpc_response(request_id, {'resourceTemplates': resources})

    def complete(self, client, request_id, argument, ref, **params):
        completions = self.template_resources.get(ref.get('uri'), (None,))[-1]
        if completions is None:
            return client.create_rpc_error(request_id, client.INVALID_PARAMS, 'completion not found')

        values = completions.get(argument.get('name'), lambda v: [])(argument['value'])

        return client.create_rpc_response(request_id, {'completion': {'values': values}})

    def read(self, client, request_id, uri, services_service, **params):
        params = {}
        f, name, mime_type, _ = self.concrete_resources.get(uri, (None,) * 4)

        if f is None:
            for template_uri, (regexp, f, name, mime_type, _, _) in self.template_resources.items():
                if match := regexp.fullmatch(uri):
                    uri = template_uri
                    params = match.groupdict()
                    break
            else:
                return client.create_rpc_error(request_id, client.INVALID_PARAMS, 'resource not found')

        try:
            data = services_service(f, uri, name, **params)
        except Exception as e:
            self.logger.exception(e)
            return client.create_rpc_error(request_id, client.INTERNAL_ERROR, str(e))

        streams = []
        for stream in data if isinstance(data, (list, tuple, types.GeneratorType)) else [data]:
            if isinstance(stream, str):
                stream = io.StringIO(stream)
            elif isinstance(stream, bytes):
                stream = io.BytesIO(stream)

            streams.append((uri, mime_type, stream))

        return client.create_rpc_streaming_response(request_id, streams)

    EXPORTS = []
    DECORATORS = [('resource', register)]
