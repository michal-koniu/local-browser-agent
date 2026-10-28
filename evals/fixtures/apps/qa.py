"""/qa/ : "Plant Shop", a small single-page app with six planted bugs, for exploratory testing tasks.

The planted bugs are listed in evals/fixtures/qa-bugs.json; never show that file to the agent. The app keeps its
cart in the page, so the server records nothing: the check scores the agent's findings only.
"""
from . import core
from .core import route, static_file


@route("GET", r"/qa/?")
def index(req):
    return static_file("qa/index.html")
