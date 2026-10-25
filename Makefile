.PHONY: test validate export check

test:
	python -m unittest discover -s tools/model_sync/tests -t .

validate:
	python -m tools.model_sync.validate

export:
	python -m tools.model_sync.export_billing -o billing.json

check: test validate
