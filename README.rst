====================================
Nagare Model Context Protocol server
====================================

Features:

  - Currently only for:
    - resources (direct and template)
    - prompts
    - tools (with services injection)
    - roots
  - Currently only on SSE protocol (not stdio nor websocket)
  - Admin commands for resources, prompts, tools and roots discovery and invocation

MCP server example
==================

.. code:: python

    from nagare.server.mcp_application import MCPApp


    class App(MCPApp):
        def __init__(self, name, dist, services_service, **config):
            services_service(super().__init__, name, dist, **config)

            self.register_tool(add)

            self.register_resource(resource1, 'examples://r1', 'r1')
            self.register_resource(resource2, 'examples://r2', 'r2')
            self.register_resource(resource3, 'examples://r3', 'r3', mime_type='text/html')
            self.register_resource(resource4, 'examples://r4', 'r4', mime_type='image/jpeg')
            self.register_resource(resource5, 'greeting://hello/{name}', 'hello')

            self.register_prompt(prompt1, 'prompt1')

    # Tools
    # -----

    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    # Resources
    # ---------

    def resource1(uri, name):
        # In-memory text resource
        return 'Resource #1'

    def resource2(uri, name):
        # In-memory binary resource
        return b'Resource #2'

    def resource3(uri, name):
        # Text stream resource
        return open('/tmp/index.html')

    def resource4(uri, name):
        # Binary stream resource
        return open('/tmp/logo.jpeg', 'rb')

    def resource4(uri, name):
        # Multiple binary stream resources
        return open('/tmp/logo1.jpeg', 'rb'), open('/tmp/logo2.jpeg', 'rb')

    # Prompts
    # -------

    def prompt1(code, language='unknown'):
        return f'Explain how this {language} code works:\n\n{code}'

Admin commands
==============

.. code:: sh

    nagare mcp info http://127.0.0.1:9000/sse

    nagare mcp tools list http://127.0.0.1:9000/sse

    nagare mcp tools call add -p a=10 -p b=20 http://127.0.0.1:9000/sse

    nagare mcp resources list http://127.0.0.1:9000/sse

    nagare mcp resources describe <uri> [-n <resource_index>] http://127.0.0.1:9000/sse

    nagare mcp resources read <uri> [-n <resource_index>] http://127.0.0.1:9000/sse

    nagare mcp prompts list http://127.0.0.1:9000/sse

    nagare mcp prompts get prompt1 -p language=python -p code='def fibo(): ...' http://127.0.0.1:9000/sse

.. note::

    Each `mcp` subcommands accepts several `--root <name> <uri>` arguments to define roots
