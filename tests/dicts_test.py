# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import json

from nagare.server.mcp.tools import Tools
from nagare.server.mcp.prototypes import proto_to_jsonschema


# Using dict[str, Any] for flexible schemas
def get_statistics(data_type: str) -> dict[str, float]:
    """Get various statistics."""
    return {'mean': 42.5, 'median': 40.0, 'std_dev': 5.2}


# ---------------------------------------------------------------------------------------------------------------------
def test_1():
    func = get_statistics

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func('xyz'))
    result = {'mean': 42.5, 'median': 40.0, 'std_dev': 5.2}

    assert schema == {
        'description': 'Get various statistics.',
        'inputSchema': {
            'properties': {'data_type': {'type': 'string'}},
            'required': ['data_type'],
            'type': 'object',
        },
        'name': 'get_statistics',
        'outputSchema': {
            'additionalProperties': {'type': 'number'},
            'type': 'object',
        },
    }
    content = response['content'][0].pop('text')
    assert response == {'isError': False, 'content': [{'type': 'text'}], 'structuredContent': result}
    assert json.loads(content) == result
