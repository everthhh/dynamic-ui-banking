.PHONY: install seed test dev api web clean catalog smoke

PY := python3

install:
	$(PY) -m pip install -r requirements.txt
	cd web && npm install

# Regenera data/bank.sqlite y data/series.parquet con semilla fija.
seed:
	$(PY) -m bank.seed

# Test de contrato del catalogo + tests de dominio.
test:
	$(PY) -m pytest -q

# Regenera los artefactos derivados del catalogo (tipos TS + fragmento de prompt).
catalog:
	$(PY) -m scripts.gen_catalog_artifacts

# Ciclo completo sin tocar la API de Anthropic (agente mockeado).
smoke:
	$(PY) -m scripts.smoke

api:
	uvicorn gateway.main:app --reload --port 8000

web:
	cd web && npm run dev

dev:
	@echo "Corre 'make api' y 'make web' en dos terminales, o usa docker compose up."

clean:
	rm -f data/bank.sqlite data/series.parquet
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
