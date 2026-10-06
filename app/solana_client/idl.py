"""Encode instructions and decode accounts using the program's Anchor IDL.

Anchor serializes with Borsh: little-endian integers, 32-byte public keys,
fixed arrays as raw bytes, unit enums as a one-byte variant index. Every
instruction and account starts with an 8-byte discriminator.
"""

import json
import struct
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey

IDL_PATH = Path(__file__).with_name("rxtrail_idl.json")

_INTS = {"u8": "<B", "u32": "<I", "i64": "<q", "u64": "<Q"}


class Idl:
    def __init__(self, raw: dict):
        self.raw = raw
        self.program_id = Pubkey.from_string(raw["address"])
        self._instructions = {ix["name"]: ix for ix in raw["instructions"]}
        self._accounts = {acc["name"]: acc for acc in raw["accounts"]}
        self._types = {t["name"]: t["type"] for t in raw.get("types", [])}
        self._errors = {e["code"]: e["name"] for e in raw.get("errors", [])}

    @classmethod
    def load(cls, path: Path = IDL_PATH) -> Idl:
        return cls(json.loads(path.read_text()))

    # -- instructions -----------------------------------------------------------

    def instruction_accounts(self, name: str) -> list[dict]:
        """Account slots in the order the program expects, with their flags."""
        return self._instructions[name]["accounts"]

    def encode_instruction(self, name: str, args: dict[str, Any]) -> bytes:
        ix = self._instructions[name]
        data = bytes(ix["discriminator"])
        for arg in ix["args"]:
            data += self._encode(arg["type"], args[arg["name"]])
        return data

    # -- accounts ---------------------------------------------------------------

    def account_discriminator(self, name: str) -> bytes:
        return bytes(self._accounts[name]["discriminator"])

    def decode_account(self, name: str, data: bytes) -> dict[str, Any]:
        expected = self.account_discriminator(name)
        if data[:8] != expected:
            raise ValueError(f"not a {name} account")
        value, _ = self._decode({"defined": {"name": name}}, data, 8)
        return value

    # -- errors -----------------------------------------------------------------

    def error_name(self, code: int) -> str | None:
        return self._errors.get(code)

    # -- borsh ------------------------------------------------------------------

    def _encode(self, kind, value) -> bytes:
        if kind == "pubkey":
            return bytes(value if isinstance(value, Pubkey) else Pubkey.from_string(value))
        if isinstance(kind, str) and kind in _INTS:
            return struct.pack(_INTS[kind], value)
        if isinstance(kind, dict) and "array" in kind:
            inner, size = kind["array"]
            if inner != "u8" or len(value) != size:
                raise ValueError(f"expected {size} bytes")
            return bytes(value)
        raise NotImplementedError(f"encoding {kind}")

    def _decode(self, kind, data: bytes, offset: int) -> tuple[Any, int]:
        if kind == "pubkey":
            return str(Pubkey.from_bytes(data[offset : offset + 32])), offset + 32
        if isinstance(kind, str) and kind in _INTS:
            fmt = _INTS[kind]
            return struct.unpack_from(fmt, data, offset)[0], offset + struct.calcsize(fmt)
        if isinstance(kind, dict) and "array" in kind:
            _, size = kind["array"]
            return bytes(data[offset : offset + size]), offset + size
        if isinstance(kind, dict) and "defined" in kind:
            definition = self._types[kind["defined"]["name"]]
            if definition["kind"] == "enum":
                return definition["variants"][data[offset]]["name"], offset + 1
            fields = {}
            for field in definition["fields"]:
                fields[field["name"]], offset = self._decode(field["type"], data, offset)
            return fields, offset
        raise NotImplementedError(f"decoding {kind}")
