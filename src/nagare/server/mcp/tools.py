# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --


from nagare.services.plugin import Plugin
from nagare.services.logging import log

from .utils import inspect_function


class Tools(Plugin, dict):
    PLUGIN_CATEGORY = 'nagare.applications'

    def __init__(self, name, dist, **config):
        super().__init__(name, dist, **config)
        self.rpc_exports = {'list': self.list, 'call': self.call}

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

    def call(self, app, request_id, name, arguments, services_service, **params):
        log.debug("Calling tool '%s' with %r", name, arguments)

        f = self[name][0]
        r = services_service(f, **arguments)

        return app.create_rpc_response(request_id, {'isError': False, 'content': [{'type': 'text', 'text': str(r)}]})
