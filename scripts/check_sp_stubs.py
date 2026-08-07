"""Every monkeypatched stub of a scanner._sp_* function must accept the real signature.

I have now shipped this same bug twice in two PRs: add a keyword to _sp_list, forget a test
double, find out from CI. Checking by grep-and-eyeball is what failed both times, so this
compares each stub's parameters against the real function's instead.

Run standalone — it only needs ast, so Python 3.9 can do it even though pytest cannot collect
tests/ here.
"""
import ast, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Real signatures, read from the source rather than imported (importing scanner needs 3.10+).
scanner_ast = ast.parse((ROOT / "api" / "scanner.py").read_text())
real = {}
for node in ast.walk(scanner_ast):
    if isinstance(node, ast.FunctionDef) and node.name.startswith("_sp_"):
        a = node.args
        real[node.name] = [p.arg for p in a.posonlyargs + a.args + a.kwonlyargs]

print("real signatures:")
for k, v in sorted(real.items()):
    print(f"  {k}({', '.join(v)})")

ok = True
print("\nstubs found in tests/:")
for path in sorted((ROOT / "tests").glob("*.py")):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "setattr"):
            continue
        if len(node.args) < 3:
            continue
        target = node.args[1]
        if not (isinstance(target, ast.Constant) and str(target.value).startswith("_sp_")):
            continue
        name = target.value
        stub = node.args[2]
        if not isinstance(stub, ast.Lambda):
            continue
        a = stub.args
        params = [p.arg for p in a.posonlyargs + a.args + a.kwonlyargs]
        want = real.get(name, [])
        # A stub may name its positionals differently; what matters is that every KEYWORD the
        # caller passes is accepted. _list calls _sp_list(tok, n, site=..., exclude_remediated=...).
        missing = [p for p in want[2:] if p not in params]
        status = "OK" if not missing and not a.kwarg else ("OK (**kw)" if a.kwarg else "MISSING")
        if missing and not a.kwarg:
            ok = False
            status = f"*** MISSING {missing}"
        print(f"  {path.name}:{node.lineno} {name}({', '.join(params)})  -> {status}")

print("\nALL STUBS CURRENT" if ok else "\n*** A STUB IS BEHIND THE REAL SIGNATURE ***")
sys.exit(0 if ok else 1)
