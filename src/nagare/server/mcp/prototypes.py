# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import inspect
import contextlib
from ast import Expr, Load, Name, Module, Constant, Subscript, FunctionDef, arg, arguments, fix_missing_locations
from typing import get_type_hints

from pydantic import Field, BaseModel, errors, json_schema, create_model

JSON_TO_PY_TYPES = {
    'string': 'str',
    'number': 'float',
    'integer': 'int',
    'boolean': 'bool',
    'array': 'list',
    'object': 'dict',
}
SIMPLE_TYPES = {str, float, int, bool}


class SchemaWithoutTitles(json_schema.GenerateJsonSchema):
    def field_title_should_be_set(self, schema):
        return False


def proto_to_jsonschema(f, name=None, description=None):
    sig = inspect.signature(f)

    params = {
        name: (
            param.annotation if param.annotation is not inspect.Parameter.empty else str,
            param.default if param.default is not inspect.Parameter.empty else Field(),
        )
        for name, param in sig.parameters.items()
        if name != 'self' and not name.endswith('_service')
    }

    input_schema = create_model('', **params).model_json_schema(schema_generator=SchemaWithoutTitles)
    del input_schema['title']

    output_schema = {}
    model = sig.return_annotation
    if model is not inspect.Signature.empty:
        if not issubclass(model, BaseModel):
            if not isinstance(model, type) or not (types := get_type_hints(model)):
                types = {'result': model}

            required = {name for name in types if not hasattr(model, name)}
            params = {name: (type_, Field() if name in required else None) for name, type_ in types.items()}
            model = create_model(model.__name__, __config__={'arbitrary_types_allowed': True}, **params)

        with contextlib.suppress(errors.PydanticInvalidForJsonSchema):
            output_schema = model.model_json_schema(schema_generator=SchemaWithoutTitles)
            if 'additionalProperties' in (result := output_schema['properties'].get('result', {})):
                output_schema = result

    return (
        {
            'name': name or f.__name__,
            'description': description or inspect.cleandoc(f.__doc__ or ''),
        }
        | {'inputSchema': input_schema}
        | ({'outputSchema': output_schema} if output_schema else {})
    )


def json_to_py_type(json_type, items):
    if json_type is None:
        return None

    r = Name(py_type, Load()) if (py_type := JSON_TO_PY_TYPES.get(json_type)) else Constant(json_type)
    if (json_type == 'array') and items:
        r = Subscript(r, json_to_py_type(items['type'], items.get('items')))

    return r


def jsonschema_to_proto(schema):
    func_name = schema['name']

    input_schema = schema['inputSchema']
    required = set(input_schema.get('required', ()))
    props = [(name, prop, name in required, prop.get('default')) for name, prop in input_schema['properties'].items()]

    output_schema = schema.get('outputSchema', {})
    result_prop = output_schema.get('properties', {}).get('result', {})
    result_type = json_to_py_type(result_prop.get('type') or output_schema.get('title'), result_prop.get('items'))

    func = FunctionDef(
        func_name,
        arguments(
            posonlyargs=[],
            args=[],
            defaults=[],
            kwonlyargs=[
                arg(name, annotation=json_to_py_type(prop.get('type'), prop.get('items'))) for name, prop, _, _ in props
            ],
            kw_defaults=[
                None if required else Constant(default if type(default) in SIMPLE_TYPES else None)
                for _, _, required, default in props
            ],
        ),
        [
            Expr(Constant(schema['description'])),
        ],
        decorator_list=[],
        returns=result_type,
    )

    globals_ = {}
    exec(compile(fix_missing_locations(Module([func], type_ignores=[])), '', 'exec'), globals_)  # noqa: S102

    return globals_[func_name]
