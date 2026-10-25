.PHONY: test validate export check

test:
	python -m unittest discover -s tools/model_sync/tests -t .

validate:
	python -m tools.model_sync.validate

# 正式导出必须带私有结算价：make export BASIS=/opt/model-data-private/billing_basis.json
export:
	python -m tools.model_sync.export_billing $(if $(BASIS),--basis $(BASIS)) -o billing.json

check: test validate
