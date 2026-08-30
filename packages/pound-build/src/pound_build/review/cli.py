"""Command-line tools for the standalone boat-hire candidate review."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pound.artifact import load_artifact
from pound.catalog.artifact import load_catalog
from pound.graph.spatial import GraphSpatialIndex

from pound_build.review.ranking import build_document, filter_catalog_to_network
from pound_build.review.store import ReviewFileError, load_document, write_document
from pound_build.review.web import create_app

_DEFAULT_CATALOG = Path("artifacts/england-catalog.pkl")
_DEFAULT_GRAPH = Path("artifacts/england.pkl")


def _generate(args: argparse.Namespace) -> int:
    output = Path(args.out)
    previous = None
    if output.exists():
        try:
            previous = load_document(output)
        except ReviewFileError as exc:
            print(f"ReviewFileError: {exc}", file=sys.stderr)
            return 1

    catalog = load_catalog(Path(args.catalog))
    graph_artifact = load_artifact(Path(args.graph))
    network_index = GraphSpatialIndex(graph_artifact.graph)
    catalog = filter_catalog_to_network(catalog, network_index)
    document = build_document(
        catalog,
        previous=previous,
        source_artifact=str(args.catalog),
    )
    write_document(output, document)
    return 0


def _serve(args: argparse.Namespace) -> int:
    create_app(Path(args.review)).run(
        host=args.host,
        port=args.port,
        debug=False,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pound-boat-review")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--catalog", type=Path, default=_DEFAULT_CATALOG)
    generate.add_argument("--graph", type=Path, default=_DEFAULT_GRAPH)
    generate.add_argument("--out", type=Path, required=True)
    generate.set_defaults(handler=_generate)

    serve = subparsers.add_parser("serve")
    serve.add_argument("--review", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5000)
    serve.set_defaults(handler=_serve)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
