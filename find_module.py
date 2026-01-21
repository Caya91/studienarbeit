import importlib.util

name = "pyerasure"

if importlib.util.find_spec(name) is None:
    print(f"{name} is NOT installed or not on sys.path")
else:
    print(f"{name} is installed and importable")