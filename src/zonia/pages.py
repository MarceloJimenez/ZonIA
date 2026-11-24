"""The static files and the HTML templates of the two web apps: Sonia's service and the recruiter dashboard."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PACKAGE_DIR = Path(__file__).parent  # src/zonia: static/ and templates/ are here


def add_static_and_templates(app: FastAPI) -> Jinja2Templates:
    """Serves src/zonia/static at /static, and returns the templates of src/zonia/templates."""
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    return Jinja2Templates(directory=PACKAGE_DIR / "templates")
