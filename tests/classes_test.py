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


# Ordinary classes with type hints work for structured output
class UserProfile:
    name: str
    age: int
    email: str | None = None

    def __init__(self, name: str, age: int, email: str | None = None):
        self.name = name
        self.age = age
        self.email = email


def get_user(user_id: str) -> UserProfile:
    """Get user profile - returns structured data."""
    return UserProfile(name='Alice', age=30, email='alice@example.com')


# Classes WITHOUT type hints cannot be used for structured output
class UntypedConfig:
    def __init__(self, setting1, setting2):
        self.setting1 = setting1
        self.setting2 = setting2


def get_config() -> UntypedConfig:
    """This returns unstructured output - no schema generated."""
    return UntypedConfig('value1', 'value2')


# ---------------------------------------------------------------------------------------------------------------------


def test_1():
    func = get_user

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func('alice'))

    assert schema == {
        'description': 'Get user profile - returns structured data.',
        'inputSchema': {
            'properties': {'user_id': {'type': 'string'}},
            'required': ['user_id'],
            'type': 'object',
        },
        'name': 'get_user',
        'outputSchema': {
            'properties': {
                'age': {'type': 'integer'},
                'email': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'default': None},
                'name': {'type': 'string'},
            },
            'required': ['name', 'age'],
            'title': 'UserProfile',
            'type': 'object',
        },
    }
    content = response['content'][0].pop('text')
    assert response == {
        'isError': False,
        'content': [{'type': 'text'}],
        'structuredContent': {'name': 'Alice', 'age': 30, 'email': 'alice@example.com'},
    }
    assert content.startswith('"<classes_test.UserProfile object at')


def test_2():
    func = get_config

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func())

    assert schema == {
        'description': 'This returns unstructured output - no schema generated.',
        'inputSchema': {'properties': {}, 'type': 'object'},
        'name': 'get_config',
    }
    content = response['content'][0].pop('text')
    assert response == {'isError': False, 'content': [{'type': 'text'}]}
    assert content.startswith('"<classes_test.UntypedConfig object')
