.PHONY: submit

submit: check-pipreqs
	pipreqs --force python_skeleton

check-pipreqs:
	@if ! command -v pipreqs &> /dev/null; then \
		echo "pipreqs not found. Installing..."; \
		pip install pipreqs; \
	fi