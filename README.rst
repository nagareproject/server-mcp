====================================
Nagare Model Context Protocol server
====================================

Features:

  - Currently only for tools and (direct) resources
  - Currently only on SSE protocol (not stdio nor websocket)
  - Admin commands for tools invocations and resources fetches available

Reverse proxy
=============

To serve SSE, a ``nginx`` with ``nchan`` module must be set as a reverse proxy. With configuration:

.. code::

    ...
    http {
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
                nchan_message_buffer_length 0;
            }
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

            self.register_direct_resource(resource1, 'examples://r1, 'r1')
            self.register_direct_resource(resource2, 'examples://r2, 'r2')
            self.register_direct_resource(resource3, 'examples://r3, 'r3', mime_type='text/html')
            self.register_direct_resource(resource4, 'examples://r4, 'r4', mime_type='image/jpeg')


    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

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

Admin commands
==============

.. code:: sh

    nagare mcp info http://127.0.0.1:9000/sse

    nagare mcp tools list http://127.0.0.1:9000/sse

    nagare mcp tools call add -p a=10 -p b=20 http://127.0.0.1:9000/sse

    nagare resources list http://127.0.0.1:9000/sse

    nagare resources describe <uri> http://127.0.0.1:9000/sse

    nagare resources read <uri> http://127.0.0.1:9000/sse
