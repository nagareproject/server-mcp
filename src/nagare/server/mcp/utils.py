# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import inspect
from ast import Expr, Load, Name, Module, Return, Constant, FunctionDef, arg, arguments, fix_missing_locations

TYPE_TO_NAME = {inspect.Parameter.empty: 'object', int: 'integer', bool: 'boolean', float: 'number', str: 'string'}
NAME_TO_TYPE = {'integer': int, 'boolean': bool, 'number': float, 'string': str}


def inspect_function(f):
    sig = inspect.signature(f)

    params = {}
    required = set()
    for name, param in sig.parameters.items():
        if name != 'self' and not name.endswith('_service'):
            has_default = param.default is not inspect.Parameter.empty
            if not has_default:
                required.add(name)

            params[name] = {'type': TYPE_TO_NAME[param.annotation]}
            if has_default:
                params[name]['default'] = param.default

    return params, required, TYPE_TO_NAME[sig.return_annotation]


def create_prototype(name, description, params, required, return_type):
    func = FunctionDef(
        name,
        arguments(
            posonlyargs=[],
            args=[],
            defaults=[],
            kwonlyargs=[arg(name, annotation=Name(NAME_TO_TYPE[type_].__name__, Load())) for name, type_ in params],
            kw_defaults=[None if name in required else Constant(None) for name, _ in params],
        ),
        [
            Expr(Constant(description)),
            Return(Constant(None)),
        ],
        decorator_list=[],
    )

    globals_ = {}
    exec(compile(fix_missing_locations(Module([func], type_ignores=[])), '', 'exec'), globals_)  # noqa: S102

    return globals_[name]
