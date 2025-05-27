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
    def __init__(self, name, dist, **config):
        super().__init__(name, dist, **config)
        self.rpc_exports = {'list': self.list, 'call': self.call}

    @property
    def entries(self):
        return [('register_tool', self.register)]

    @property
    def infos(self):
        return {'listChanged': False} if self else {}

    def register(self, f, func_name=None):
        self[func_name or f.__name__] = f

    def list(self, app, request_id, **params):
        tools = []
        for name, f in sorted(self.items()):
            params, required, return_type = inspect_function(f)

            tools.append(
                {
                    'name': name,
                    'description': f.__doc__ or '',
                    'inputSchema': {
                        'properties': params,
                        'required': tuple(required),
                        'title': f.__doc__ or '',
                        'type': return_type,
                    },
                }
            )

        return app.create_rpc_response(request_id, {'tools': tools})

    def call(self, app, request_id, name, arguments, services_service, **params):
        log.debug("Calling tool '%s' with %r", name, arguments)

        f = self[name]
        r = services_service(f, **arguments)

        return app.create_rpc_response(request_id, {'isError': False, 'content': [{'type': 'text', 'text': str(r)}]})
