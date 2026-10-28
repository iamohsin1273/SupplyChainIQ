.PHONY: install pipeline test lint dashboard
install:
	python -m pip install -e '.[app,test]'
pipeline:
	PYTHONPATH=src python -m supplychainiq.pipeline
test:
	PYTHONPATH=src pytest -q
lint:
	ruff check src tests streamlit_app

dashboard:
	PYTHONPATH=src streamlit run streamlit_app/app.py
