====================================
Nagare Model Context Protocol server
====================================

Features:

  - Currently only for tools publication
  - Currently only on SSE protocol (not stdio nor websocket)
  - Admin commands for tools invocations available

Reverse proxy
=============

To serve SSE, a `nginx` with `nchan` module must be set as a reverse proxy. With configuration:

.. code::

    ...
    server {
        listen       9000;
        server_name  localhost;

        location ~ /sub/([a-f0-9-]+)$ {
            internal;

            nchan_subscriber;
            nchan_channel_id $1;

            nchan_subscribe_request /_sub/$nchan_channel_id;
        }

        location ~ /_sub/([a-f0-9-]+)$ {
            internal;

            # Nagare MCP server url
            proxy_pass http://127.0.0.1:8080;
        }

        location / {
            # Nagare MCP server url
            proxy_pass http://127.0.0.1:8080;
        }
    }

    server {
        listen      127.0.0.1:9001;
        server_name localhost;

        location ~ /pub/([a-f0-9-]+)$ {
            nchan_publisher;
            nchan_channel_id $1;
        }
    }
    ...

MCP server example
==================

.. code:: python

    from nagare.server.mcp_application import MCPApp


    class App(MCPApp):
        def __init__(self, name, dist, services_service, **config):
            services_service(super().__init__, name, dist, **config)

            self.register_tool(add)


    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

Admin commands
==============

.. code:: shell

    nagare mcp info http://127.0.0.1:9000/sse

    nagare mcp tools list http://127.0.0.1:9000/see

    nagare mcp tools call add -p a=10 -p b=20 http://127.0.0.1:9000/sse
