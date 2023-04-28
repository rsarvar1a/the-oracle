
import argparse
import client
import json


def main ():
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default = "config.json")
    args = parser.parse_args()
    
    with open(args.config, "r") as f:
        options = json.load(f)

    client = client.Client(options)
    client.run()


if __name__ == "__main__":
    main()