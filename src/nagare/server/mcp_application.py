# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import sys

from .mcp.application import MCPApp  # noqa: F401

sys.modules[__name__].__dict__.update(MCPApp.exports())
sys.modules[__name__].__dict__.update(MCPApp.decorators())
