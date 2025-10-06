.PHONY: build-products validate-products

build-products:
	python tools/build_products.py --descriptions-url "$${DESCRIPTIONS_URL:-https://raw.githubusercontent.com/go2telegram/media/main/media/descriptions/%D0%9F%D0%BE%D0%BB%D0%BD%D0%BE%D0%B5%20%D0%BE%D0%BF%D0%B8%D1%81%D0%B0%D0%BD%D0%B8%D0%B5%20%D0%BF%D1%80%D0%BE%D0%B4%D1%83%D0%BA%D1%82%D0%BE%D0%B2%20vilavi%20(%D0%BE%D1%84%D0%BE%D1%80%D0%BC%D0%BB%D0%B5%D0%BD%D0%BE%20v3).txt}"

validate-products:
	python -c "import json, jsonschema; sch=json.load(open('app/data/products.schema.json', encoding='utf-8')); data=json.load(open('app/data/products.json', encoding='utf-8')); jsonschema.validate(data, sch); print('schema OK')"
