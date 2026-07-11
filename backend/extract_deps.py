import os
import ast

builtin = set(['sys', 'os', 'math', 'time', 'datetime', 'logging', 'json', 're', 'uuid', 'io', 'pathlib', 'asyncio', 'typing', 'collections', 'itertools', 'functools', 'urllib', 'hashlib', 'ssl', 'inspect', 'traceback', 'concurrent', 'enum', 'random', 'subprocess', 'copy', 'decimal', 'contextvars', 'contextlib', 'sqlite3', 'tempfile', 'shutil', 'hmac', 'base64', 'types'])

all_imports = set()

for r, d, f in os.walk('.'):
    for file in f:
        if file.endswith('.py'):
            try:
                tree = ast.parse(open(os.path.join(r, file), 'r', encoding='utf-8', errors='ignore').read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            all_imports.add(n.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        all_imports.add(node.module.split('.')[0])
            except Exception as e:
                pass

third_party = all_imports - builtin - set(['app', 'tests', 'migrations', 'scripts', 'loadtest'])
print('\n'.join(sorted(third_party)))
