# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import inspect

from nagare.services.plugin import Plugin
from nagare.services.logging import log


class Tools(Plugin, dict):
    CONVERTER = {inspect.Parameter.empty: 'object', int: 'integer', bool: 'boolean', float: 'number', str: 'string'}

    @property
    def entries(self):
        return [('register_tool', self.register)]

    @property
    def infos(self):
        return {'listChanged': False} if self else {}

    def register(self, f, func_name=None):
        sig = inspect.signature(f)

        params = {}
        required = set()
        for name, param in sig.parameters.items():
            if name != 'self':
                has_default = param.default is not inspect.Parameter.empty
                if not has_default:
                    required.add(name)

                params[name] = {'type': self.CONVERTER[param.annotation]}
                if has_default:
                    params[name]['default'] = param.default

        self[func_name or f.__name__] = (
            f,
            {
                'description': f.__doc__ or '',
                'inputSchema': {
                    'properties': params,
                    'required': tuple(required),
                    'title': f.__doc__ or '',
                    'type': self.CONVERTER[sig.return_annotation],
                },
            },
        )

    def list_rpc(self, app, channel, request_id, **params):
        app.send_json(
            channel,
            request_id,
            {'tools': [{'name': name} | meta for name, (_, meta) in sorted(self.items())]},
        )

    def call_rpc(self, app, channel, request_id, name, arguments, services_service, **params):
        log.debug("Calling tool '%s' with %r", name, arguments)

        f = self[name][0]
        r = services_service(f, **arguments)

        app.send_json(channel, request_id, {'isError': False, 'content': [{'type': 'text', 'text': str(r)}]})
