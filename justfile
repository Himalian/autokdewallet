all:
	just -l

# install the package into ~/.autokdewallet and the user unit
install:
	#!/usr/bin/env bash
	set -euo pipefail
	dest="${HOME}/.autokdewallet"
	mkdir -p "$dest"
	chmod 700 "$dest"

	# Replace the installed package so stale modules cannot linger.
	rm -rf "$dest/autokdewallet"
	cp -r src/autokdewallet "$dest/autokdewallet"
	find "$dest/autokdewallet" -type d -name __pycache__ -prune -exec rm -rf {} +

	# Remove the flat layout used before the package refactor.
	rm -f "$dest/unlock.py" "$dest/calculate_hash.py" "$dest/get_salt.py"

	if [[ -f password.cred ]]; then
		if [[ -e "$dest/password.cred" ]]; then
			echo "Kept existing $dest/password.cred" >&2
			echo "Remove ./password.cred or the installed file before replacing it." >&2
			exit 1
		fi
		mv password.cred "$dest/password.cred"
		chmod 600 "$dest/password.cred"
		echo "Moved password.cred to $dest/password.cred"
	fi

	mkdir -p "${HOME}/.config/systemd/user"
	cp systemd/kwallet_auto_unlock.service "${HOME}/.config/systemd/user/kwallet_auto_unlock.service"
	echo "Installed package in $dest and unit in ${HOME}/.config/systemd/user"
	if [[ ! -f "$dest/password.cred" ]]; then
		echo "Next: just generate_password 'YOUR_KWALLET_PASSWORD'"
		echo "Then: just enable"
	else
		echo "Next: just enable"
	fi

# enable the user service for the next login
enable:
	systemctl --user daemon-reload
	systemctl --user reenable kwallet_auto_unlock.service
	systemctl --user reset-failed kwallet_auto_unlock.service

# install runtime files and enable the user service
setup: install enable

# encrypt the wallet password into ~/.autokdewallet/password.cred
generate_password password="":
	#!/usr/bin/env bash
	set -euo pipefail
	password={{quote(password)}}
	if [[ -z "$password" ]]; then
		echo "Usage: just generate_password 'YOUR_KWALLET_PASSWORD'" >&2
		exit 1
	fi
	dest="${HOME}/.autokdewallet"
	mkdir -p "$dest"
	chmod 700 "$dest"
	printf '%s' "$password" | systemd-creds encrypt --user - "$dest/password.cred"
	chmod 600 "$dest/password.cred"
	echo "Wrote $dest/password.cred"

# run the unlocker installed in ~/.autokdewallet
run:
	#!/usr/bin/env bash
	set -euo pipefail
	dest="${HOME}/.autokdewallet"
	if [[ ! -d "$dest/autokdewallet" ]]; then
		echo "Runtime is not installed. Run: just install" >&2
		exit 1
	fi
	cd "$dest"
	exec python3 -u -m autokdewallet

# run the unit tests
test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf "${HOME}/.autokdewallet/autokdewallet/__pycache__"
