# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from nagare.services.plugin import Plugin

from .utils import inspect_function


class Prompts(Plugin, dict):
    def __init__(self, name, dist, **config):
        super().__init__(name, dist, **config)
        self.rpc_exports = {'list': self.list, 'complete': self.complete, 'get': self.get}

    @classmethod
    def decorators(cls):
        return [('prompt', cls.register)]

    @property
    def infos(self):
        return {'listChanged': False} if self else {}

    def register(self, f, name=None, description=None, arguments=()):
        name = name or f.__name__
        description = description or f.__doc__ or ''
        self[name] = (f, description)

        return f

    def list(self, app, request_id, **params):
        prompts = []
        for name, (f, description) in sorted(self.items()):
            params, required, return_type = inspect_function(f)

            prompts.append(
                {'name': name, 'arguments': [{'name': name, 'required': name in required} for name in params]}
            )

        return app.create_rpc_response(request_id, {'prompts': prompts})

    def complete(self, app, request_id, argument, ref, **params):
        return app.create_rpc_response(request_id, {'completion': {'values': []}})

    def get(self, app, request_id, name, arguments, services_service, **kw):
        prompt = self[name][0]
        result = services_service(prompt, **arguments)

        return app.create_rpc_response(
            request_id, {'messages': [{'role': 'user', 'content': {'type': 'text', 'text': result}}]}
        )
