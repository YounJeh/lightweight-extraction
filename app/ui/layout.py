from fasthtml.common import A, Div, Nav, Titled


def page(title: str, *content):
    nav = Nav(
        A("Champs", href="/fields"),
        " · ",
        A("Extraction", href="/extraction"),
    )
    return Titled(title, nav, Div(*content))
