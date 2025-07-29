# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from base64 import b64encode
from operator import attrgetter
from itertools import chain

import pydantic_core
from filetype import guess_mime

from nagare.services.plugin import Plugin
from nagare.services.logging import log

from .prototypes import jsonschema_to_proto, proto_to_jsonschema


class ToolResult(dict):
    pass


def ToolText(text):
    return ToolResult(type='text', text=str(text))


def ToolImage(data, mime_type=None):
    return ToolResult(
        type='image',
        mimeType=mime_type or guess_mime(data) or 'application/octet-stream',
        data=b64encode(data).decode('ascii'),
    )


def ToolTextResource(uri, text):
    return ToolResult(type='resource', resource={'uri': uri, 'text': text, 'mimeType': 'text/plain'})


def ToolBlobResource(uri, blob, mime_type=None):
    return ToolResult(
        type='resource',
        resource={'uri': uri, 'blob': b64encode(blob).decode('ascii')} | ({'mimeType': mime_type} if mime_type else {}),
    )


class Tools(Plugin, dict):
    PLUGIN_CATEGORY = 'nagare.applications'

    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602

    @property
    def rpc_exports(self):
        return {'list': self.list, 'call': self.call}

    @property
    def infos(self):
        return {'listChanged': False} if self else {}

    def register(self, f, name=None, description=None):
        schema = proto_to_jsonschema(f, name, description)
        proto = jsonschema_to_proto(schema)
        self[proto.__name__] = (proto, 'outputSchema' in schema, f, description)

        return f

    def list(self, app, request_id, **params):
        schemas = [proto_to_jsonschema(f, name, description) for name, (_, _, f, description) in sorted(self.items())]

        return app.create_rpc_response(request_id, {'tools': schemas})

    @classmethod
    def to_content(cls, result):
        if result is None:
            return []

        if not isinstance(result, (str | ToolResult | list | tuple)):
            result = pydantic_core.to_json(result, fallback=str, indent=2).decode()

        if isinstance(result, str):
            result = ToolText(result)

        return list(chain(*[cls.to_content(item) for item in result])) if isinstance(result, list | tuple) else [result]

    @staticmethod
    def create_tool_error(msg):
        return {'isError': True, 'content': [{'type': 'text', 'text': msg}]}

    @classmethod
    def create_tool_response(cls, with_structured_content, result):
        content = cls.to_content(result)
        response = {'isError': False, 'content': content}

        if content and with_structured_content:
            structured_content = pydantic_core.to_jsonable_python(result, fallback=attrgetter('__dict__'))
            if not isinstance(structured_content, dict):
                structured_content = {'result': structured_content}

            response |= {'structuredContent': structured_content}

        return response

    def call(self, app, request_id, name, services_service, arguments=None, **params):
        arguments = arguments or {}
        log.debug("Calling tool '%s' with %r", name, arguments)

        proto, with_structured_content, f, _ = self.get(name, (None,) * 4)
        if proto is None:
            return app.create_rpc_error(request_id, self.METHOD_NOT_FOUND, 'tool not found')

        try:
            proto(**arguments)
        except Exception as e:
            return app.create_rpc_error(request_id, self.INVALID_PARAMS, str(e))

        try:
            response = self.create_tool_response(with_structured_content, services_service(f, **arguments))
        except Exception as e:
            self.logger.exception(e)
            response = self.create_tool_error(str(e))

        return app.create_rpc_response(request_id, response)

    EXPORTS = [ToolImage, ToolTextResource, ToolBlobResource]
    DECORATORS = [('tool', register)]
