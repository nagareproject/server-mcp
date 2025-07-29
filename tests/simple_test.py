# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from nagare.server.mcp.tools import Tools
from nagare.server.mcp.prototypes import proto_to_jsonschema


def no_result():
    pass


def str_result():
    """Only a str result."""
    return 'hello'


def str_result2() -> str:
    return 'hello'


def list_str_result() -> list[str]:
    return 'hello', 'world'


def int_result() -> int:
    return 42


def get_temperature(city: str) -> float:
    """Get temperature as a simple float."""
    return 22.5


def bytes_result() -> bytes:
    return b'\x00\x01\x02'


def tuple_result() -> tuple[int, str]:
    return (42, 'hello')


def bool_false_result() -> bool:
    return False


def bool_true_result() -> bool:
    return True


def list_cities() -> list[str]:
    """Get a list of cities."""
    return ['London', 'Paris', 'Tokyo']


# ---------------------------------------------------------------------------------------------------------------------


def test_no_result():
    func = no_result

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': '',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'no_result',
    }
    assert response == {'isError': False, 'content': []}


def test_str_result():
    func = str_result

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': 'Only a str result.',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'str_result',
    }
    assert response == {'isError': False, 'content': [{'type': 'text', 'text': 'hello'}]}


def test_str_result2():
    func = str_result2

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': '',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'str_result2',
        'outputSchema': {
            'properties': {'result': {'type': 'string'}},
            'required': ['result'],
            'title': 'str',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [{'type': 'text', 'text': 'hello'}],
        'structuredContent': {'result': 'hello'},
    }


def test_list_str_result():
    func = list_str_result

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': '',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'list_str_result',
        'outputSchema': {
            'properties': {'result': {'items': {'type': 'string'}, 'type': 'array'}},
            'required': ['result'],
            'title': 'list',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [{'type': 'text', 'text': 'hello'}, {'type': 'text', 'text': 'world'}],
        'structuredContent': {'result': ['hello', 'world']},
    }


def test_int_result():
    func = int_result

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': '',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'int_result',
        'outputSchema': {
            'properties': {'result': {'type': 'integer'}},
            'required': ['result'],
            'title': 'int',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [{'type': 'text', 'text': '42'}],
        'structuredContent': {'result': 42},
    }


def test_float():
    func = get_temperature

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func('london'))

    assert schema == {
        'description': 'Get temperature as a simple float.',
        'inputSchema': {
            'properties': {'city': {'type': 'string'}},
            'required': ['city'],
            'type': 'object',
        },
        'name': 'get_temperature',
        'outputSchema': {
            'properties': {'result': {'type': 'number'}},
            'required': ['result'],
            'title': 'float',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [{'type': 'text', 'text': '22.5'}],
        'structuredContent': {'result': 22.5},
    }


def test_bytes():
    func = bytes_result

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': '',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'bytes_result',
        'outputSchema': {
            'properties': {'result': {'format': 'binary', 'type': 'string'}},
            'required': ['result'],
            'title': 'bytes',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [{'type': 'text', 'text': '"\\u0000\\u0001\\u0002"'}],
        'structuredContent': {'result': '\x00\x01\x02'},
    }


def test_tuple_result():
    func = tuple_result

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': '',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'tuple_result',
        'outputSchema': {
            'properties': {
                'result': {
                    'maxItems': 2,
                    'minItems': 2,
                    'prefixItems': [{'type': 'integer'}, {'type': 'string'}],
                    'type': 'array',
                }
            },
            'required': ['result'],
            'title': 'tuple',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [{'type': 'text', 'text': '42'}, {'type': 'text', 'text': 'hello'}],
        'structuredContent': {'result': [42, 'hello']},
    }


def test_bool_false():
    func = bool_false_result

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': '',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'bool_false_result',
        'outputSchema': {
            'properties': {'result': {'type': 'boolean'}},
            'required': ['result'],
            'title': 'bool',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [{'type': 'text', 'text': 'false'}],
        'structuredContent': {'result': False},
    }


def test_bool_true():
    func = bool_true_result

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': '',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'bool_true_result',
        'outputSchema': {
            'properties': {'result': {'type': 'boolean'}},
            'required': ['result'],
            'title': 'bool',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [{'type': 'text', 'text': 'true'}],
        'structuredContent': {'result': True},
    }


def test_list():
    func = list_cities

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': 'Get a list of cities.',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'list_cities',
        'outputSchema': {
            'properties': {'result': {'items': {'type': 'string'}, 'type': 'array'}},
            'required': ['result'],
            'title': 'list',
            'type': 'object',
        },
    }
    assert response == {
        'isError': False,
        'content': [
            {'type': 'text', 'text': 'London'},
            {'type': 'text', 'text': 'Paris'},
            {'type': 'text', 'text': 'Tokyo'},
        ],
        'structuredContent': {'result': ['London', 'Paris', 'Tokyo']},
    }
