from copy import deepcopy

from graph import dependency_order

graph = {"app": ["lib", "lib"], "lib": ["core"], "z": [], "extra": ["core"]}
before = deepcopy(graph)
assert dependency_order(graph) == ["core", "extra", "lib", "app", "z"]
assert graph == before and dependency_order({}) == []
for graph in [{"a": ["b"], "b": ["a"]}, {"a": ["a"]}]:
    try:
        dependency_order(graph)
    except ValueError:
        pass
    else:
        raise AssertionError("cycle accepted")
