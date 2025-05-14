# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import inspect

CONVERTER = {inspect.Parameter.empty: 'object', int: 'integer', bool: 'boolean', float: 'number', str: 'string'}


def inspect_function(f):
    sig = inspect.signature(f)

    params = {}
    required = set()
    for name, param in sig.parameters.items():
        if name != 'self':
            has_default = param.default is not inspect.Parameter.empty
            if not has_default:
                required.add(name)

            params[name] = {'type': CONVERTER[param.annotation]}
            if has_default:
                params[name]['default'] = param.default

    return params, required, CONVERTER[sig.return_annotation]
