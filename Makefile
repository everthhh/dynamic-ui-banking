.PHONY: install seed test dev api web clean catalog fixtures smoke check build

PY := python3

install:
	$(PY) -m pip install -r requirements.txt
	cd web && npm install

# Regenera data/bank.sqlite y data/series.parquet con semilla fija.
seed:
	$(PY) -m bank.seed

# Artefactos derivados del catalogo: fragmento del prompt + tipos TypeScript.
catalog:
	$(PY) -m scripts.gen_catalog_artifacts

# Guion grabado del front (web/src/fixtures/demo.json) con numeros reales.
fixtures:
	$(PY) -m scripts.gen_fixtures

# Ciclo completo intencion -> tools -> UI -> accion -> UI, sin tocar la API.
smoke:
	$(PY) -m scripts.smoke

test:
	$(PY) -m pytest

# Lo que debe pasar antes de empujar nada.
check: test smoke
	$(PY) -m scripts.gen_catalog_artifacts --check
	$(PY) -m bank.seed --check
	cd web && npm run typecheck

build:
	cd web && npm run build

api:
	uvicorn gateway.main:app --reload --port 8000

web:
	cd web && npm run dev

dev:
	@echo "Dos terminales:  make api   |   make web"
	@echo "Sin API key:     make web y abre http://localhost:5173/?mock=1"

clean:
	rm -f data/bank.sqlite data/bank.sqlite-wal data/bank.sqlite-shm data/series.parquet
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf web/dist web/node_modules/.vite
