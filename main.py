import pathlib
import logging
import argparse
import asyncio

import pytomlpp
import appdirs
from multidict import CIMultiDict
from aiohttp import web

import quicclient

APP_NAME = "QUICProxy"
APP_AUTHOR = "iv-org"

CONFIG_DIRECTORY = pathlib.Path(f"{appdirs.user_config_dir(APP_NAME, APP_AUTHOR)}")
CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = pathlib.Path(f"{appdirs.user_config_dir(APP_NAME, APP_AUTHOR)}/config.toml")
CONFIG_FILE.touch(exist_ok=True)


with open(f"{CONFIG_FILE}") as config:
    config = pytomlpp.loads(config.read())
if not config:
    config = {"listen": "0.0.0.0:7192", "open_connections": 5}
routes = web.RouteTableDef()


def process_cli_args():
    # Taken from https://stackoverflow.com/a/20663028
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-d', '--debug',
        help="Print lots of debugging statements",
        action="store_const", dest="loglevel", const=logging.DEBUG,
        default=logging.WARNING,
    )
    parser.add_argument(
        '-v', '--verbose',
        help="Be verbose",
        action="store_const", dest="loglevel", const=logging.INFO,
    )
    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel)


@routes.post("/")
async def post(request):
    arguments = await request.json()
    post_data = str(arguments.get("data", ""))
    post_data = post_data if post_data else None
    method = arguments["method"]

    # Create heders
    intermediate_header_processing = [(k, v) for k, v in arguments.get("headers", {}).items()]
    processed_headers = CIMultiDict(intermediate_header_processing)

    packaged_request = quicclient.InvidiousRequest(url=arguments["url"], method=method, headers=processed_headers,
                                                   content=post_data)
    result = {}
    await request_processor.requests_to_do.put([packaged_request, result])
    await packaged_request.completed.wait()

    if result["headers"][":status"] == "304":
        return web.Response(body=b"", headers=result["headers"], status=304)
    else:
        return web.Response(body=result["response"], headers=result["headers"])


async def main():
    [asyncio.create_task(request_processor.request_worker()) for _ in range(config.get("open_connections", 5))]
    app = web.Application()
    app.add_routes(routes)
    return app


request_processor = quicclient.RequestProcessor()
if __name__ == '__main__':
    process_cli_args()

    address, port = config.get("listen", "0.0.0.0:7912").split(":")
    web.run_app(main(), port=port, host=address)
