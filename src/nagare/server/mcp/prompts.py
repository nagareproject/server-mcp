# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from base64 import b64encode

from filetype import guess_mime

from nagare.services.plugin import Plugin

from .prototypes import jsonschema_to_proto, proto_to_jsonschema


class PromptResult(dict):
    pass


def PromptText(text, role='user'):
    return PromptResult(role=role, content={'type': 'text', 'text': str(text)})


def PromptImage(data, role='user', mime_type=None):
    return PromptResult(
        role=role,
        content={
            'type': 'image',
            'mimeType': mime_type or guess_mime(data) or 'application/octet-stream',
            'data': b64encode(data).decode('ascii'),
        },
    )


def PromptTextResource(uri, text, role='user'):
    return PromptResult(
        role=role, content={'type': 'resource', 'resource': {'uri': uri, 'text': text, 'mimeType': 'text/plain'}}
    )


def PromptBlobResource(uri, blob, role='user', mime_type=None):
    return PromptResult(
        role=role,
        content={
            'type': 'resource',
            'resource': {'uri': uri, 'blob': b64encode(blob).decode('ascii')}
            | ({'mimeType': mime_type} if mime_type else {}),
        },
    )


class Prompts(Plugin, dict):
    PLUGIN_CATEGORY = 'nagare.applications'

    INTERNAL_ERROR = -32603

    @property
    def rpc_exports(self):
        return {'list': self.list, 'complete': self.complete, 'get': self.get}

    @property
    def infos(self):
        return {'listChanged': False} if self else {}

    def register(self, f, name=None, description=None, descriptions=None, completions=None):
        schema = proto_to_jsonschema(f, name, description)
        proto = jsonschema_to_proto(schema)
        self[proto.__name__] = (proto, f, description, descriptions or {}, completions or {})

        return f

    def list(self, client, request_id, **params):
        prompts = []
        for name, (_, f, description, descriptions, _) in sorted(self.items()):
            schema = proto_to_jsonschema(f, name, description)
            properties = schema['inputSchema']['properties']
            required = set(properties.get('required', []))

            prompts.append(
                {
                    'name': name,
                    'description': schema['description'],
                    'arguments': [
                        {'name': name, 'required': name in required, 'description': descriptions.get(name, '')}
                        for name in properties
                    ],
                }
            )

        return client.create_rpc_response(request_id, {'prompts': prompts})

    def complete(self, client, request_id, argument, ref, **params):
        name = ref.get('name')
        if name not in self:
            return client.create_rpc_error(request_id, client.INVALID_PARAMS, 'completion not found')

        values = self[name][-1].get(argument.get('name'), lambda v: [])(argument['value'])

        return client.create_rpc_response(request_id, {'completion': {'values': values}})

    def get(self, client, request_id, name, arguments, services_service, **kw):
        if name not in self:
            return client.create_rpc_error(request_id, client.INVALID_PARAMS, 'prompt not found')

        proto, f = self[name][:2]

        try:
            proto(**arguments)
        except Exception as e:
            return client.create_rpc_error(request_id, client.INVALID_PARAMS, str(e))

        try:
            results = services_service(f, **arguments)
        except Exception as e:
            self.logger.exception(e)
            return client.create_rpc_error(request_id, client.INTERNAL_ERROR, str(e))

        response = {
            'messages': [
                (result if isinstance(result, PromptResult) else PromptText(result))
                for result in (results if isinstance(results, (list, tuple)) else [results])
            ]
        }

        return client.create_rpc_response(request_id, response)

    EXPORTS = [PromptText, PromptImage, PromptTextResource, PromptBlobResource]
    DECORATORS = [('prompt', register)]
