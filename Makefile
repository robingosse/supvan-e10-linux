.PHONY: test install uninstall package

test:
	cd driver && cargo fmt --check && cargo test --workspace && cargo check --all-targets
	cd label-studio && PYTHONPATH=. python3 -m pytest -q

install:
	./install.sh

uninstall:
	./uninstall.sh

package:
	./scripts/make-source-tarball.sh
