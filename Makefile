PYTHON ?= python

.PHONY: install crawl import-graph run-api compile

install:
	python3 -m pip install -r requirements.txt

crawl:
	python3 -m data_pipeline

import-graph:
	python3 scripts/import_neo4j.py

run-api:
	uvicorn kg.api:app --reload

compile:
	python3 -m compileall kg data_pipeline scripts
