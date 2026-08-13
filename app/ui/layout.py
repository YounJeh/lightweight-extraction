from fasthtml.common import A, Div, H1, Main, Title

_NAV_ITEMS = [
    ("fields", "Champs", "/fields"),
    ("extraction", "Extraction", "/extraction"),
]


def _active_key(title: str) -> str:
    return "fields" if title == "Champs" else "extraction"


def _sidebar(active: str):
    return Div(
        Div("Lightweight Extraction", cls="sidebar-title"),
        Div(
            *[
                A(label, href=href, cls="active" if key == active else "")
                for key, label, href in _NAV_ITEMS
            ],
            cls="sidebar-nav",
        ),
        cls="sidebar",
    )


def page(title: str, *content):
    return (
        Title(title),
        Div(
            _sidebar(_active_key(title)),
            Main(H1(title), *content, cls="content"),
            cls="app-shell",
        ),
    )
