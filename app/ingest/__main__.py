"""CLI: python -m app.ingest [chunks|registry] [--path ./policies]

chunks (default) ingests policy_chunks; registry ingests policy_documents +
policy_document_links. --path defaults to the POLICY_DIR env var (see
docs/DATA_CONTRACT.md).
"""

import argparse
import asyncio
import logging
import sys

from app.config import settings
from app.ingest.dq import IngestError
from app.ingest.pipeline import run_ingest
from app.ingest.registry_pipeline import run_registry_ingest


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    parser = argparse.ArgumentParser(description="Ingest policy documents.")
    parser.add_argument(
        "command",
        nargs="?",
        default="chunks",
        choices=["chunks", "registry"],
        help="Which ingest to run (default: chunks).",
    )
    parser.add_argument(
        "--path", default=None, help="Directory of policy files to ingest (default: POLICY_DIR env var)."
    )
    args = parser.parse_args()
    path = args.path or settings.policy_dir

    try:
        if args.command == "registry":
            asyncio.run(run_registry_ingest(path))
        else:
            asyncio.run(run_ingest(path))
    except IngestError as exc:
        logging.getLogger(__name__).error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
