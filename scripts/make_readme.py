from __future__ import unicode_literals

import io
import re
import subprocess
import typing

README_FILE = 'README.md'
EXAMPLE_FILE = 'src/redd_harvest/data/example.yml'
EXE = 'redd-harvest'
HELP = '--help'

def get_help_text(cmd:typing.List[str]):
    result = subprocess.run(cmd, stdout=subprocess.PIPE)
    text = result.stdout.decode('utf-8')
    return text.strip()

def get_text_after(text:str, string:str):
    return text[text.index(string) + len(string) + 1:]

def build_options_section(exe: str, flag: str) -> str:
    helptext = get_help_text([exe, flag])
    helptext = get_text_after(helptext, 'Options:')
    commandtext = get_text_after(helptext, "Commands:")
    commands = []
    for cmd in commandtext.splitlines():
        matched = re.search(r'^(\w+)\s', cmd.strip())
        if matched:
            commands.append(matched.group(1).strip())
    helptext = f'Global Options:\n{helptext}'
    for cmd in commands:
        text = get_help_text([exe, cmd, flag])
        cmd_opt_text = get_text_after(text, "Options:")
        helptext = f'{helptext}\n\nOptions for \'{cmd}\':\n{cmd_opt_text}'
    return helptext

options_text = build_options_section(EXE, HELP)

with io.open(EXAMPLE_FILE, encoding='utf-8') as f:
    exampletext = f.read()

if isinstance(exampletext, bytes):
    exampletext = exampletext.decode('utf-8')

with io.open(README_FILE, encoding='utf-8') as f:
    oldreadme = f.read()

option_header_anchor = '# Options'
option_footer_anchor = '# Configuration'
example_header_anchor = '## Config File Structure'
example_footer_anchor = '# Behavior'

option_header = oldreadme[:oldreadme.index(option_header_anchor)]
option_footer = oldreadme[oldreadme.index(option_footer_anchor):oldreadme.index(example_header_anchor)]

example_header = oldreadme[oldreadme.index(example_header_anchor):oldreadme.index(example_header_anchor) + len(example_header_anchor) + 1]
example_footer = oldreadme[oldreadme.index(example_footer_anchor):]

options = f'{option_header_anchor}\n```\n{options_text}\n```\n\n'
exampletext = f'```yaml\n{exampletext}\n```\n\n'

with io.open(README_FILE, 'w', encoding='utf-8') as f:
    f.write(option_header)
    f.write(options)
    f.write(option_footer)
    f.write(example_header)
    f.write(exampletext)
    f.write(example_footer)