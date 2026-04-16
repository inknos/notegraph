"""Sphinx configuration for notegraph documentation."""

project = "notegraph"
author = ""
version = "0.1.0"
release = version

extensions = [
    "cyclopts.sphinx_ext",
]

html_theme = "sphinx_rtd_theme"

man_pages = [
    ("index", "notegraph", "Note graph generator for GitHub and Jira issues", [""], 1),
]
