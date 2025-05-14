# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from ast import Expr, Name, Module, Return, Constant, FunctionDef, arg, arguments, fix_missing_locations

CONVERTER = {'integer': int, 'boolean': bool, 'number': float, 'string': str}


def create_prototype(name, description, return_type, params, required):
    func = FunctionDef(
        name,
        arguments(
            kwonlyargs=[arg(name, annotation=Name(CONVERTER[type_].__name__)) for name, type_ in params],
            kw_defaults=[None if name in required else Constant(None) for name, _ in params],
        ),
        [
            Expr(Constant(description)),
            Return(Constant(None)),
        ],
    )

    globals_ = {}
    exec(compile(fix_missing_locations(Module([func])), '', 'exec'), globals_)  # noqa: S102

    return globals_[name]
