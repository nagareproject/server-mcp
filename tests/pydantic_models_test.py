# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import json

from pydantic import Field, BaseModel

from nagare.server.mcp.tools import Tools
from nagare.server.mcp.prototypes import proto_to_jsonschema


# Using Pydantic models for rich structured data
class WeatherData(BaseModel):
    """Weather information structure."""

    temperature: float = Field(description='Temperature in Celsius')
    humidity: float = Field(description='Humidity percentage')
    condition: str
    wind_speed: float


def get_weather(city: str) -> WeatherData:
    """Get weather for a city - returns structured data."""
    # Simulated weather data
    return WeatherData(
        temperature=72.5,
        humidity=45.0,
        condition='sunny',
        wind_speed=5.2,
    )


# ---------------------------------------------------------------------------------------------------------------------


def test_1():
    func = get_weather

    schema = proto_to_jsonschema(func)
    response = Tools.create_tool_response('outputSchema' in schema, func('london'))
    result = {'temperature': 72.5, 'humidity': 45.0, 'condition': 'sunny', 'wind_speed': 5.2}

    assert schema == {
        'description': 'Get weather for a city - returns structured data.',
        'inputSchema': {
            'properties': {'city': {'type': 'string'}},
            'required': ['city'],
            'type': 'object',
        },
        'name': 'get_weather',
        'outputSchema': {
            'description': 'Weather information structure.',
            'properties': {
                'condition': {'type': 'string'},
                'humidity': {'description': 'Humidity percentage', 'type': 'number'},
                'temperature': {'description': 'Temperature in Celsius', 'type': 'number'},
                'wind_speed': {'type': 'number'},
            },
            'required': ['temperature', 'humidity', 'condition', 'wind_speed'],
            'title': 'WeatherData',
            'type': 'object',
        },
    }
    content = response['content'][0].pop('text')
    assert response == {'isError': False, 'content': [{'type': 'text'}], 'structuredContent': result}
    assert json.loads(content) == result
