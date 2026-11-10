import os
from collections import defaultdict as dd


def top_level_function(x):
    os.path.join("a", "b")
    return dd(list)


def lazy_loader():
    import json

    return json.dumps({})


class Greeter:
    def __init__(self, name):
        self.name = name

    def greet(self):
        return helper(self.name)


def helper(name):
    return f"hello {name}"
