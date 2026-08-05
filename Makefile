.PHONY: install demo test serve lint seed

install:
	python -m pip install -e ".[dev]"

demo:
	python -m ai_content_pipeline.cli demo

serve:
	python -m ai_content_pipeline.cli serve

test:
	python -m unittest discover -s tests -v

lint:
	ruff check src tests

seed:
	python -m ai_content_pipeline.cli seed

