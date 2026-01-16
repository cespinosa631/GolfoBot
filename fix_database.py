#!/usr/bin/env python3
"""Fix all database functions to use get_async_session()"""

with open('aoe3/database.py', 'r') as f:
    content = f.read()

# Functions that need fixing - add finally blocks before the next function
functions_to_fix = [
    'get_all_players',
    'update_player_elo',
    'get_leaderboard',
    'add_match',
    'get_player_matches',
    'get_civilization',
    'upsert_civilization',
    'add_strategy',
    'get_strategies',
    'vote_strategy',
    'get_strategy_votes'
]

# The pattern is to find "return" statements at the end of functions
# and add "finally: await session.close()" before them

import re

# Replace pattern: look for functions that have session = get_async_session() but no finally
# Add finally block before the function ends

lines = content.split('\n')
new_lines = []
i = 0

while i < len(lines):
    line = lines[i]
    new_lines.append(line)
    
    # If we find "session = get_async_session()" followed by "try:"
    if 'session = get_async_session()' in line and i + 1 < len(lines) and 'try:' in lines[i+1]:
        # Look for the corresponding return statement(s) at the same or lower indentation
        indent_level = len(line) - len(line.lstrip())
        
        # Skip ahead to find where we need to add finally
        j = i + 2
        in_function = True
        last_return_line = None
        
        while j < len(lines) and in_function:
            current_line = lines[j]
            current_indent = len(current_line) - len(current_line.lstrip())
            
            # Check if we're at the next function definition (same or less indentation as "session =")
            if current_line.strip().startswith('async def ') and current_indent <= indent_level:
                in_function = False
                # Insert finally block before this line
                if last_return_line is not None:
                    new_lines.insert(last_return_line + 1, ' ' * (indent_level + 4) + 'finally:')
                    new_lines.insert(last_return_line + 2, ' ' * (indent_level + 8) + 'await session.close()')
                break
            
            # Track the last return we saw
            if 'return ' in current_line or current_line.strip() == 'return':
                last_return_line = len(new_lines) + (j - i - 1)
            
            j += 1
    
    i += 1

content = '\n'.join(new_lines)

with open('aoe3/database.py', 'w') as f:
    f.write(content)

print("Fixed database.py")
