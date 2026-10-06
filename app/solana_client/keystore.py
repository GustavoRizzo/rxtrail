"""Named keypair files, in the format of the Solana CLI (`solana-keygen`).

Each participant of the demo has a file `<name>.json`: a JSON array of the
64 keypair bytes (32 secret seed + 32 public key), created 0600 in a 0700
directory kept out of git. In production each participant would hold their
own key on their own device; the program does not care where a signature
comes from, only that it is there.
"""

import json
import os
import re
from pathlib import Path

from solders.keypair import Keypair

# Names become file names: keep them boring so they can never escape the dir.
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class KeyNotFoundError(LookupError):
    pass


class FileKeyStore:
    def __init__(self, directory: Path):
        self._dir = Path(directory)

    def exists(self, name: str) -> bool:
        return bool(_NAME.match(name)) and self._path(name).exists()

    def create(self, name: str) -> Keypair:
        path = self._path(name)
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        keypair = Keypair()
        # O_EXCL: never overwrite an existing key, even in a race.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(list(bytes(keypair)), file)
        return keypair

    def keypair(self, name: str) -> Keypair:
        try:
            raw = json.loads(self._path(name).read_text())
        except FileNotFoundError:
            raise KeyNotFoundError(f"no key named {name!r} in {self._dir}") from None
        return Keypair.from_bytes(bytes(raw))

    def _path(self, name: str) -> Path:
        if not _NAME.match(name):
            raise ValueError(f"invalid key name {name!r}: use lowercase letters, digits and dashes")
        return self._dir / f"{name}.json"
