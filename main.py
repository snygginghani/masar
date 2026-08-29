"""Development entrypoint for Masar."""

from masar_app.app import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=True)
