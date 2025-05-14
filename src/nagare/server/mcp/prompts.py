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

    @property
    def entries(self):
        return [('register_prompt', self.register_prompt)]

    @property
    def infos(self):
        return {'listChanged': False} if self else {}

    def register_prompt(self, f, name, description='', arguments=()):
        self[name] = f

    def list(self, app, channel, request_id, **params):
        prompts = []
        for name, f in sorted(self.items()):
            params, required, return_type = inspect_function(f)

            prompts.append(
                {'name': name, 'arguments': [{'name': name, 'required': name in required} for name in params]}
            )

        app.send_json(channel, request_id, {'prompts': prompts})

    def complete(self, app, channel, request_id, argument, ref, **params):
        app.send_json(channel, request_id, {'completion': {'values': []}})

    def get(self, app, channel, request_id, name, arguments, services_service, **kw):
        prompt = self[name]
        result = services_service(prompt, **arguments)

        app.send_json(
            channel, request_id, {'messages': [{'role': 'user', 'content': {'type': 'text', 'text': result}}]}
        )
