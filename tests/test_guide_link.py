"""The plugin's Guide button and menu open the PDF for the installed version: that PDF must be in the repo."""
import importlib.util
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_guide_link_points_at_this_versions_pdf():
    spec = importlib.util.spec_from_file_location(
        "links", os.path.join(ROOT, "qgis_plugin", "road_furniture_designer", "links.py"))
    links = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(links)
    v = links.version()
    url = links.guide_url()
    name = f"Road_Furniture_Designer_{v}_User_Guide.pdf"
    assert v and url.endswith(f"/blob/v{v}/docs/user-guide/{name}")
    assert os.path.exists(os.path.join(ROOT, "docs", "user-guide", name))
    meta = open(os.path.join(ROOT, "qgis_plugin", "road_furniture_designer", "metadata.txt"), encoding="utf-8").read()
    assert links.GUIDE_FOLDER in meta                      # the plugin store page says where the manual is
