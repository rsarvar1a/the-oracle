from . import client
from . import formatter

import argparse
import json
import logging


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default="config.json")
    parser.add_argument("-d", "--debug", action="store_true")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        options = json.load(f)

    log_level = logging.DEBUG if args.debug else logging.INFO

    instance = client.Client(options=options, logging_level=log_level)
    instance.run()


if __name__ == "__main__":
    main()
