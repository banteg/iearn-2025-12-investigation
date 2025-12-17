#!/usr/bin/env python3

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SOURCIFY_BASE_URL = "https://sourcify.dev/server"
DEFAULT_CHAIN_ID = 1
DEFAULT_INPUT_PATH = pathlib.Path("sources/address-label.json")
DEFAULT_OUTPUT_DIR = pathlib.Path("contract_sources")


ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class AddressLabel:
    address: str
    label: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _http_get_json(url: str, *, timeout_s: float, retries: int, backoff_s: float) -> tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "iearn-2025-12-investigation/contract_sources_downloader",
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
            if status in (404,):
                return status, payload
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


def _safe_relative_file_path(repo_path: str, address: str) -> pathlib.Path:
    parts = [p for p in repo_path.split("/") if p]
    address_lower = address.lower()

    address_index = None
    for idx, part in enumerate(parts):
        if part.lower() == address_lower:
            address_index = idx
            break

    if address_index is None:
        rel_parts = [pathlib.PurePosixPath(repo_path).name]
    else:
        rel_parts = parts[address_index + 1 :]
        if not rel_parts:
            rel_parts = [pathlib.PurePosixPath(repo_path).name]

    rel_path = pathlib.Path(*rel_parts)
    if rel_path.is_absolute() or any(p in ("..", "") for p in rel_path.parts):
        rel_path = pathlib.Path(pathlib.PurePosixPath(repo_path).name)
    return rel_path


def _write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def fetch_and_write_contract(
    *,
    chain_id: int,
    entry: AddressLabel,
    output_root: pathlib.Path,
    timeout_s: float,
    retries: int,
    backoff_s: float,
) -> dict[str, Any]:
    address = entry.address
    address_lower = address.lower()
    url = f"{SOURCIFY_BASE_URL}/files/any/{chain_id}/{address}"

    http_status, payload = _http_get_json(url, timeout_s=timeout_s, retries=retries, backoff_s=backoff_s)

    contract_dir = output_root / str(chain_id) / address_lower
    contract_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "chainId": chain_id,
        "address": address_lower,
        "label": entry.label,
        "endpoint": url,
        "retrievedAt": _utc_now_iso(),
        "httpStatus": http_status,
        "status": None,
        "filesSaved": 0,
        "error": None,
    }

    if http_status != 200:
        result["error"] = payload.get("error") if isinstance(payload, dict) else str(payload)
        _write_text(contract_dir / "sourcify_error.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")
        _write_text(contract_dir / "sourcify.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    status = payload.get("status") if isinstance(payload, dict) else None
    files = payload.get("files") if isinstance(payload, dict) else None
    if status not in ("full", "partial") or not isinstance(files, list):
        result["error"] = "Unexpected Sourcify response shape"
        _write_text(contract_dir / "sourcify_error.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")
        _write_text(contract_dir / "sourcify.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    result["status"] = status

    (contract_dir / "sourcify_error.json").unlink(missing_ok=True)

    saved = 0
    for f in files:
        if not isinstance(f, dict):
            continue
        content = f.get("content")
        repo_path = f.get("path") or f.get("name") or ""
        if not isinstance(content, str) or not isinstance(repo_path, str) or not repo_path:
            continue

        rel_path = _safe_relative_file_path(repo_path, address)
        if rel_path.name in ("sourcify.json", "sourcify_error.json"):
            rel_path = pathlib.Path("sources") / rel_path.name

        out_path = contract_dir / rel_path
        _write_text(out_path, content)
        saved += 1

    result["filesSaved"] = saved
    _write_text(contract_dir / "sourcify.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _load_address_labels(path: pathlib.Path) -> list[AddressLabel]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected a JSON array in {path}")

    out: list[AddressLabel] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Expected object at index {idx}")
        address = item.get("address")
        label = item.get("label", "")
        if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
            raise ValueError(f"Invalid address at index {idx}: {address!r}")
        if not isinstance(label, str):
            label = str(label)
        out.append(AddressLabel(address=address, label=label))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Download verified contract sources from Sourcify.")
    parser.add_argument("--chain-id", type=int, default=DEFAULT_CHAIN_ID)
    parser.add_argument("--input", type=pathlib.Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=pathlib.Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-workers", type=int, default=min(12, (os.cpu_count() or 4)))
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--backoff-s", type=float, default=1.0)
    args = parser.parse_args()

    entries = _load_address_labels(args.input)
    output_root = args.output_dir
    output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        futures = [
            executor.submit(
                fetch_and_write_contract,
                chain_id=args.chain_id,
                entry=entry,
                output_root=output_root,
                timeout_s=args.timeout_s,
                retries=args.retries,
                backoff_s=args.backoff_s,
            )
            for entry in entries
        ]

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: (r.get("chainId", 0), r.get("address", "")))
    index = {
        "generatedAt": _utc_now_iso(),
        "chainId": args.chain_id,
        "input": str(args.input),
        "outputDir": str(args.output_dir),
        "total": len(results),
        "downloaded": sum(1 for r in results if r.get("httpStatus") == 200),
        "missing": sum(1 for r in results if r.get("httpStatus") == 404),
        "errors": sum(1 for r in results if r.get("httpStatus") not in (200, 404)),
        "results": results,
    }
    _write_text(output_root / "index.json", json.dumps(index, indent=2, sort_keys=True) + "\n")

    downloaded = index["downloaded"]
    total = index["total"]
    print(f"Downloaded {downloaded}/{total} contracts into {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
