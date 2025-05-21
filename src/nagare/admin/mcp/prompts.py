# --
# Copyright (c) 2008-2025 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --
from pydoc import plaintext

import yaml

from nagare.admin import admin

from .utils import create_prototype
from .commands import Command


class Prompts(admin.Commands):
    DESC = 'MCP prompts subcommands'


class Prompt(Command):
    def create_prompts(self):
        return {
            prompt['name']: create_prototype(
                prompt['name'],
                prompt.get('description', ''),
                None,
                [(argument['name'], 'string') for argument in prompt['arguments']],
                {argument['name'] for argument in prompt['arguments'] if argument['required']},
            )
            for prompt in self.send('prompts/list')['prompts']
        }


class List(Prompt):
    DESC = 'List the prompts'

    def run(self):
        print('Available prompts:\n')
        for _, proto in sorted(self.create_prompts().items()):
            print(' -', plaintext.document(proto))

        return 0


class Get(Prompt):
    DESC = 'Complete a prompt'

    def set_arguments(self, parser):
        parser.add_argument('prompt')
        parser.add_argument('-p', '--param', action='append', dest='params')

        super().set_arguments(parser)

    def run(self, prompt, params):
        prompts = self.create_prompts()

        func = prompts.get(prompt)
        if func is None:
            print('Error: tool not found!')
            return -1

        try:
            args = {}
            for param in params or ():
                name, value = param.split('=', 1)
                args[name] = func.__annotations__.get(name, lambda v: v)(value)

            func(**args)
        except Exception as e:
            print('Error:', e)
            return -1

        result = self.send('prompts/get', name=prompt, arguments=args)
        print(yaml.dump(result['messages']))

        return 0
