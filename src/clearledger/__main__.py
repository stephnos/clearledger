import argparse

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Run the ClearLedger local demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("clearledger.app:create_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
