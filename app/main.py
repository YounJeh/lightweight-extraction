from fasthtml.common import Titled, fast_app, serve

app, rt = fast_app()


@rt("/")
def get():
    return Titled("Lightweight Extraction")


if __name__ == "__main__":
    # `app/main.py` lives inside the `app` package (run via `python -m app.main`),
    # so FastHTML's default module-stem guess ("main") would miss the package
    # prefix that uvicorn's reloader needs to re-import the app.
    serve(appname="app.main")
