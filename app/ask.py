"""CLI: python -m app.ask "<question>" """

import argparse
import asyncio
import sys

from app.answering import answer_question
from app.db import close_pool


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Ask the policy chatbot a question.")
    parser.add_argument("question", help="The question to ask, in Mongolian.")
    args = parser.parse_args()

    async def run() -> str:
        try:
            return await answer_question(args.question)
        finally:
            await close_pool()

    answer = asyncio.run(run())
    print(answer)


if __name__ == "__main__":
    main()
