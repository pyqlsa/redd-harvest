.PHONY: install clean all readme

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
EXE := redd-harvest

.DEFAULT_GOAL := install

$(VENV)/bin/activate: setup.py setup.cfg pyproject.toml
	python3 -m venv $(VENV)
	$(PIP) install -e .

install: $(VENV)/bin/activate

clean:
	rm -rf $(VENV)
	find . -type d -name '__pycache__' -exec rm -rf {} +

README.md: src/**/*.py src/**/data/*.yml scripts/make_readme.py
	. $(VENV)/bin/activate; $(PYTHON) scripts/make_readme.py

readme: install README.md

all: clean install
