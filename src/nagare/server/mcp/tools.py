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
from nagare.services.logging import log

from .utils import create_prototype, inspect_function


class Result(dict):
    pass


def TextResult(text):
    return Result(type='text', text=str(text))


def ImageResult(mime_type, data):
    if isinstance(data, bytes):
        data = b64encode(data).decode('ascii')

    return Result(type='image', mimeType=mime_type, data=data)


def TextResourceResult(uri, text):
    return Result(type='resource', resource={'uri': uri, 'text': text, 'mimeType': 'text/plain'})


def BlobResourceResult(uri, blob, mime_type=None):
    if isinstance(blob, bytes):
        blob = b64encode(blob).decode('ascii')

    return Result(type='resource', resource={'uri': uri, 'blob': blob} | ({'mimeType': mime_type} if mime_type else {}))


class Tools(Plugin, dict):
    PLUGIN_CATEGORY = 'nagare.applications'

    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602

    def __init__(self, name, dist, **config):
        super().__init__(name, dist, **config)
        self.rpc_exports = {'list': self.list, 'call': self.call}

    @classmethod
    def exports(cls):
        return [TextResult, ImageResult, TextResourceResult, BlobResourceResult]

    @classmethod
    def decorators(cls):
        return [('tool', cls.register)]

    @property
    def infos(self):
        return {'listChanged': False} if self else {}

    def register(self, f, name=None, description=None):
        name = name or f.__name__
        description = description or f.__doc__ or ''
        self[name] = (f, description)

        return f

    def list(self, app, request_id, **params):
        tools = []
        for name, (f, description) in sorted(self.items()):
            params, required, return_type = inspect_function(f)

            tools.append(
                {
                    'name': name,
                    'description': description,
                    'inputSchema': {'properties': params, 'required': tuple(required), 'type': return_type},
                }
            )

        return app.create_rpc_response(request_id, {'tools': tools})

    def call(self, app, request_id, name, services_service, arguments=None, **params):
        arguments = arguments or {}
        log.debug("Calling tool '%s' with %r", name, arguments)

        f, _ = self.get(name, (None, None))
        if f is None:
            return app.create_rpc_error(request_id, self.METHOD_NOT_FOUND, 'tool not found')

        try:
            params, required, return_type = inspect_function(f)
            params = [(name, meta['type']) for name, meta in params.items()]

            create_prototype(name, '', params, required, return_type)(**arguments)
        except Exception as e:
            return app.create_rpc_error(request_id, self.INVALID_PARAMS, str(e))

        try:
            results = services_service(f, **arguments)
        except Exception as e:
            self.logger.exception(e)

            return app.create_rpc_response(request_id, {'isError': True, 'content': [TextResult(str(e))]})

        response = {}
        for result in results if isinstance(results, (list, tuple)) else [results]:
            if isinstance(result, Result):
                response.setdefault('content', []).append(result)
            elif isinstance(result, dict):
                response['structuredContent'] = result
            else:
                response.setdefault('content', []).append(TextResult(result))

        return app.create_rpc_response(request_id, {'isError': False} | response)
