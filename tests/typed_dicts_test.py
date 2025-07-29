# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import json
from typing import TypedDict

from nagare.server.mcp.tools import Tools
from nagare.server.mcp.prototypes import proto_to_jsonschema


# Using TypedDict for simpler structures
class LocationInfo(TypedDict):
    latitude: float
    longitude: float
    name: str


def get_location(address: str) -> LocationInfo:
    """Get location coordinates."""
    return LocationInfo(latitude=51.5074, longitude=-0.1278, name='London, UK')


# ---------------------------------------------------------------------------------------------------------------------


def test_1():
    func = get_location

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func('london'))
    result = {'latitude': 51.5074, 'longitude': -0.1278, 'name': 'London, UK'}

    assert schema == {
        'description': 'Get location coordinates.',
        'inputSchema': {
            'properties': {'address': {'type': 'string'}},
            'required': ['address'],
            'type': 'object',
        },
        'name': 'get_location',
        'outputSchema': {
            'properties': {
                'latitude': {'type': 'number'},
                'longitude': {'type': 'number'},
                'name': {'type': 'string'},
            },
            'required': ['latitude', 'longitude', 'name'],
            'title': 'LocationInfo',
            'type': 'object',
        },
    }
    content = response['content'][0].pop('text')
    assert response == {'isError': False, 'content': [{'type': 'text'}], 'structuredContent': result}
    assert json.loads(content) == result
