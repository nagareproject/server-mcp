====================================
Nagare Model Context Protocol server
====================================

Features:

- Available capabilities:

- tools (with services injection)
- resources (direct and template)
- prompts
- roots
- optional completions for resources and prompts arguments

- Available utilities:

- server can send logs to the client (`client_service.progress()`)
- server can send progresses to the client (`client_service.log()`)

- STDIO and SSE protocols support
- Admin commands for discovery and invocation of SSE server methods

Protocols
=========

SSE events
----------

The publisher must be a HTTP publisher with only threads pool

.. code:: ini

    [publisher]
    type = gunicorn  # or waitress

STDIO
-----

The publisher must be ``mcp-stdio``, installed from ``nagare-publishers-mcp-stdio`` package

To not interfer with stdout communications, don't ``print`` and configure loggers to not emit to stdout:

.. code:: ini

    [publisher]
    type = mcp-stdio

    [logging]
      [[logger]]
        [[[root]]]
        handlers = root

      [[handlers]]
        [[[root]]]
        class = logging.FileHandler
        args = "('/tmp/mcp.log', 'w')"

MCP server example
==================

.. code:: python

    import time

    from nagare.server.mcp_application import MCPApp, tool, resource, prompt


    class App(MCPApp):
        pass


    # Tools
    # -----

    @tool(description='n1 + n2')
    def add(a: int, b: int):
        """Add two numbers."""
        return a + b

    @tool
    def grettings(client_service):
        for i in range(5):
            time.sleep(i)
            client_service.progress(i, 5)

        client_service.log('debug', 'ready to answer...')

        return 'Hello'

    # Resources
    # ---------

    @resource()
    def resource1(uri, name):
        return 'Resource #1'

    @resource(uri='r1')
    def resource1_1(uri, name):
        return 'Hello', 'world!'

    @resource('r2', name='r2', mime_type='application/octet-stream')
    def resource2(uri, name):
        return b'Resource #2'

    @resource(uri='r3', name='r3', mime_type='text/plain')
    def resource3(uri, name):
        return open('/tmp/f.py')

    @resource(mime_type='application/pdf')
    def resource4(uri, name):
        return open('/tmp/doc.pdf', 'rb')

    def complete_city(city):
        return [name for name in ['paris', 'new-york', 'sao-paulo', 'sidney'] if name.startswith(city.lower())]

    @resource('weather://{city}/current', 't1', completions={'city': complete_city)
    def template1(uri, name, city):
        return 'Weather for city {}'.format(city)

    # Prompts
    # -------

    @prompt()
    def prompt1(code, language='unknown'):
        return f'Explain how this {language} code works:\n\n{code}'


Admin commands
==============

.. code:: sh

    nagare mcp info http://127.0.0.1:9000/sse

    nagare mcp tools list http://127.0.0.1:9000/sse

    nagare mcp tools call add -p a=10 -p b=20 http://127.0.0.1:9000/sse

    nagare mcp resources list http://127.0.0.1:9000/sse

    nagare mcp resources read <uri> [-n <resource_index>] http://127.0.0.1:9000/sse

    nagare mcp prompts list http://127.0.0.1:9000/sse

    nagare mcp prompts get prompt1 -p language=python -p code='def fibo(): ...' http://127.0.0.1:9000/sse

.. note::

    All ``mcp`` subcommands accept several ``--root <name> <uri>`` arguments to define client roots
