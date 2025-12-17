#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ETHERSCAN_V2_API_URL = "https://api.etherscan.io/v2/api"
DEFAULT_CHAIN_ID = 1
DEFAULT_SOURCIFY_INDEX_PATH = pathlib.Path("contract_sources/index.json")
DEFAULT_OUTPUT_ROOT = pathlib.Path("contract_sources")

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_relative_path(file_path: str) -> pathlib.Path:
    posix = pathlib.PurePosixPath(file_path)
    if posix.is_absolute() or ".." in posix.parts:
        return pathlib.Path(posix.name)
    return pathlib.Path(*[p for p in posix.parts if p not in ("", ".")])


def _write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(content, encoding="utf-8")
    except UnicodeEncodeError:
        path.write_text(content, encoding="utf-8", errors="backslashreplace")


def _write_json(path: pathlib.Path, obj: Any) -> None:
    _write_text(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def _http_get_json(url: str, *, timeout_s: float, retries: int, backoff_s: float) -> tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "iearn-2025-12-investigation/etherscan_sources_downloader",
    }

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout_s) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode("utf-8"))
            return status, payload
        except HTTPError as e:
            last_error = e
            status = getattr(e, "code", 0) or 0
            try:
                payload = json.loads(e.read().decode("utf-8"))
            except Exception:
                payload = {"error": str(e)}
            if status in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(backoff_s * (2**attempt))
                continue
            return status, payload
        except URLError as e:
            last_error = e
            if attempt < retries:
                time.sleep(backoff_s * (2**attempt))
                continue
            raise

    raise RuntimeError(f"Unexpected retry loop exit: {last_error!r}")


def _parse_etherscan_multifile_source(source_code: str) -> dict[str, str] | None:
    s = source_code.strip()
    if not s:
        return None

    if s.startswith("{{") and s.endswith("}}"):
        s = s[1:-1].strip()

    if not (s.startswith("{") and s.endswith("}")):
        return None

    try:
        obj = json.loads(s)
    except Exception:
        return None

    sources = obj.get("sources")
    if not isinstance(sources, dict):
        return None

    out: dict[str, str] = {}
    for name, entry in sources.items():
        if not isinstance(name, str) or not name:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("content"), str):
            out[name] = entry["content"]
        elif isinstance(entry, str):
            out[name] = entry
    return out or None


def _guess_extension(result_obj: dict[str, Any]) -> str:
    compiler_type = (result_obj.get("CompilerType") or "").strip().lower()
    if compiler_type == "vyper":
        return ".vy"
    if compiler_type == "solc":
        return ".sol"
    compiler_version = (result_obj.get("CompilerVersion") or "").strip().lower()
    if "vyper" in compiler_version:
        return ".vy"
    if compiler_version.startswith("v") or "solc" in compiler_version:
        return ".sol"
    return ".txt"


def fetch_etherscan_source(
    *,
    chain_id: int,
    address: str,
    api_key: str,
    output_root: pathlib.Path,
    label: str | None,
    timeout_s: float,
    retries: int,
    backoff_s: float,
    throttle_s: float,
) -> dict[str, Any]:
    if not ADDRESS_RE.fullmatch(address):
        raise ValueError(f"Invalid address: {address}")

    address_lower = address.lower()

    params = {
        "apikey": api_key,
        "chainid": str(chain_id),
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
    }
    endpoint = f"{ETHERSCAN_V2_API_URL}?{urlencode(params)}"

    contract_dir = output_root / str(chain_id) / address_lower
    contract_dir.mkdir(parents=True, exist_ok=True)

    if throttle_s > 0:
        time.sleep(throttle_s)

    http_status, payload = _http_get_json(endpoint, timeout_s=timeout_s, retries=retries, backoff_s=backoff_s)

    result: dict[str, Any] = {
        "chainId": chain_id,
        "address": address_lower,
        "label": label,
        "endpoint": endpoint,
        "retrievedAt": _utc_now_iso(),
        "httpStatus": http_status,
        "apiStatus": None,
        "apiMessage": None,
        "filesSaved": 0,
        "error": None,
    }

    _write_json(contract_dir / "etherscan_response.json", payload)

    if http_status != 200 or not isinstance(payload, dict):
        result["error"] = "Unexpected HTTP response from Etherscan"
        _write_json(contract_dir / "etherscan.json", result)
        return result

    api_status = payload.get("status")
    api_message = payload.get("message")
    result["apiStatus"] = api_status
    result["apiMessage"] = api_message

    if api_status != "1":
        result["error"] = payload.get("result") if isinstance(payload.get("result"), str) else "Etherscan error"
        _write_json(contract_dir / "etherscan.json", result)
        return result

    api_result = payload.get("result")
    if not isinstance(api_result, list) or not api_result:
        result["error"] = "Empty Etherscan result"
        _write_json(contract_dir / "etherscan.json", result)
        return result

    first = api_result[0]
    if not isinstance(first, dict):
        result["error"] = "Unexpected Etherscan result shape"
        _write_json(contract_dir / "etherscan.json", result)
        return result

    source_code = first.get("SourceCode")
    if not isinstance(source_code, str) or not source_code.strip():
        result["error"] = "No SourceCode in Etherscan response"
        _write_json(contract_dir / "etherscan.json", result)
        return result

    sources = _parse_etherscan_multifile_source(source_code)
    saved = 0

    sources_dir = contract_dir / "sources"
    if sources is not None:
        for name, content in sources.items():
            rel = _safe_relative_path(name)
            if not rel.suffix:
                rel = rel.with_suffix(_guess_extension(first))
            _write_text(sources_dir / rel, content)
            saved += 1
    else:
        contract_name = (first.get("ContractName") or "").strip()
        ext = _guess_extension(first)
        filename = f"{contract_name}{ext}" if contract_name else f"contract{ext}"
        _write_text(sources_dir / filename, source_code)
        saved = 1

    result["filesSaved"] = saved
    _write_json(contract_dir / "etherscan.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download contract sources for Sourcify-missing addresses via the Etherscan v2 API."
    )
    parser.add_argument("--chain-id", type=int, default=DEFAULT_CHAIN_ID)
    parser.add_argument("--sourcify-index", type=pathlib.Path, default=DEFAULT_SOURCIFY_INDEX_PATH)
    parser.add_argument("--output-root", type=pathlib.Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--api-key", type=str, default=os.environ.get("ETHERSCAN_API_KEY", ""))
    parser.add_argument("--dry-run", action="store_true", help="Only print the addresses that would be fetched.")
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--backoff-s", type=float, default=1.0)
    parser.add_argument("--throttle-s", type=float, default=0.2)
    args = parser.parse_args()

    if not args.api_key and not args.dry_run:
        raise SystemExit("Missing Etherscan API key. Set ETHERSCAN_API_KEY or pass --api-key.")

    idx = json.loads(args.sourcify_index.read_text(encoding="utf-8"))
    results = idx.get("results")
    if not isinstance(results, list):
        raise SystemExit(f"Unexpected Sourcify index shape in {args.sourcify_index}")

    missing: list[dict[str, Any]] = [r for r in results if isinstance(r, dict) and r.get("httpStatus") == 404]

    addresses_to_fetch: list[tuple[str, str | None]] = []
    for r in missing:
        address = r.get("address")
        label = r.get("label")
        if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
            continue
        if int(address, 16) in range(1, 10):
            continue
        addresses_to_fetch.append((address, label if isinstance(label, str) else None))

    if args.dry_run:
        for address, label in addresses_to_fetch:
            if label:
                print(f"{address} {label}")
            else:
                print(address)
        print(f"Would fetch {len(addresses_to_fetch)} addresses from Etherscan v2.")
        return 0

    out: list[dict[str, Any]] = []
    for address, label in addresses_to_fetch:
        out.append(
            fetch_etherscan_source(
                chain_id=args.chain_id,
                address=address,
                api_key=args.api_key,
                output_root=args.output_root,
                label=label,
                timeout_s=args.timeout_s,
                retries=args.retries,
                backoff_s=args.backoff_s,
                throttle_s=args.throttle_s,
            )
        )

    out.sort(key=lambda r: r.get("address", ""))
    index = {
        "generatedAt": _utc_now_iso(),
        "chainId": args.chain_id,
        "sourcifyIndex": str(args.sourcify_index),
        "outputRoot": str(args.output_root),
        "totalAttempted": len(out),
        "downloaded": sum(1 for r in out if r.get("filesSaved", 0) > 0),
        "errors": sum(1 for r in out if r.get("filesSaved", 0) == 0),
        "results": out,
    }
    _write_json(args.output_root / "etherscan_index.json", index)
    print(f"Etherscan downloaded sources for {index['downloaded']}/{index['totalAttempted']} attempted addresses.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
