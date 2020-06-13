import argparse
import json
import os
import time

import requests

import dataclasses
import logging
from typing import *


L = logging.getLogger(__name__)


class RequestFailed(RuntimeError):
    def __init__(self, reason: str):
        super("request failed: " + reason)


class Client:
    def __init__(self, token):
        self.baseurl = "https://slack.com/api"
        self.default_header = {"content-type": "application/x-www-form-urlencoded"}
        self.token = token

    def _get(self, url, params) -> requests.Response:
        headers = self.default_header
        params["token"] = self.token
        res = requests.get(url, headers=headers, params=params)
        return self._decode_response(res)

    def _post(self, url, data) -> Any:
        headers = self.default_header
        data["token"] = self.token
        res = requests.post(url, headers=headers, data=data)
        return self._decode_response(res)

    def _decode_response(self, res: requests.Response) -> Any:
        if res.status_code != 200:
            raise RequestFailed(f"status_code isn't 200 ({res.status_code})")
        return res.json()

    def auth_test(self):
        return self._get(self.baseurl + "/auth.test", {})

    def conversations_list(self, cursor: str = None):
        params = {"types": "public_channel,private_channel,mpim"}
        if cursor is not None:
            params["cursor"] = cursor
        return self._get(self.baseurl + "/conversations.list", params)

    def conversations_members(self, channel: str, cursor: str = None):
        params = {"channel": channel}
        if cursor is not None:
            params["cursor"] = cursor
        return self._get(self.baseurl + "/conversations.members", params)

    def conversations_history(self, channel: str, cursor: str = None):
        params = {"channel": channel}
        if cursor is not None:
            params["cursor"] = cursor
        return self._get(self.baseurl + "/conversations.history", params)

    def conversations_join(self, channel: str):
        params = {"channel": channel}
        return self._post(self.baseurl + "/conversations.join", params)

    def users_list(self, cursor: str = None):
        params = {}
        if cursor is not None:
            params["cursor"] = cursor
        return self._get(self.baseurl + "/users.list", params)

    def users_profile_set(self, user: str, key: str, value: str):
        params = {"user": user, "name": key, "value": value}
        return self._post(self.baseurl + "/users.profile.set", params)


def get_channels(cli: Client) -> List[Any]:
    L.info("fetching channel metadata...")
    channels: List[Any] = []
    next_cursor = None
    while next_cursor != "":
        data = cli.conversations_list(next_cursor)
        if not data["ok"]:
            raise RuntimeError(f"request failed: (data={data})")
        channels += data["channels"]
        next_cursor = data["response_metadata"]["next_cursor"]

    L.info("fetching channel members...")
    for c in channels:
        L.info(f"fetching channel members for channel {c['name']}...")

        c["members"] = []
        if c["is_archived"]:
            L.info(f"channel {c['name']} is archived, skipped")
            continue

        next_cursor = None
        try:
            while next_cursor != "":
                data = cli.conversations_members(c["id"])
                if not data["ok"]:
                    raise RuntimeError(f"request failed: (channel={c}, data={data})")
                c["members"] += data["members"]
                next_cursor = data["response_metadata"]["next_cursor"]
        except Exception as e:
            pass

    return channels


def get_users(cli: Client) -> List[Any]:
    L.info("fetching user metadata...")
    users: List[Any] = []
    next_cursor = None
    while next_cursor != "":
        data = cli.users_list(next_cursor)
        if not data["ok"]:
            raise RuntimeError(f"request failed: (data={data})")
        users += data["members"]
        next_cursor = data["response_metadata"]["next_cursor"]

    return users


def get_messages(cli: Client, channel: Any) -> List[Any]:
    L.info(f"fetching messages for channel {channel['name']}...")
    messages: List[Any] = []
    next_cursor = None
    while next_cursor != "":
        data = cli.conversations_history(channel["id"], next_cursor)
        if not data["ok"]:
            raise RuntimeError(f"request failed: (data={data})")
        messages += data["messages"]

        if not data["has_more"]:
            next_cursor = ""
        else:
            next_cursor = data["response_metadata"]["next_cursor"]

    return messages


def append_download_token(msg: Any, download_token: str):
    if not "files" in msg:
        return

    for f in msg["files"]:
        if f["mimetype"].startswith("image"):
            for s in [64, 80, 360, 480, 160, 720, 800, 960, 1024]:
                try:
                    f[f"thumb_{s}"] += f"?t={download_token}"
                except Exception as e:
                    L.debug("exception occured in append_download_token, ignored...")


def output(dest: str, channels: List[Any], users: List[Any], messages: Dict[str, List[Any]], download_token: Optional[str] = None):
    os.makedirs(dest, exist_ok=True)

    with open(f"{dest}/channels.json", "w") as f:
        f.write(json.dumps(channels))

    with open(f"{dest}/users.json", "w") as f:
        f.write(json.dumps(users))

    for channel in channels:
        channel_dir = f"{dest}/{channel['name']}"
        os.makedirs(channel_dir, exist_ok=True)

        if not channel["name"] in messages:
            continue

        msgs = {}
        for msg in messages[channel["name"]]:
            if download_token is not None:
                append_download_token(msg, download_token)

            t = time.gmtime(float(msg["ts"]))
            key = f"{t.tm_year:04}-{t.tm_mon:02}-{t.tm_mday:02}"
            if not key in msgs:
                msgs[key] = []
            msgs[key].append(msg)

        for key in msgs.keys():
            with open(f"{channel_dir}/{key}.json", "w") as f:
                f.write(json.dumps(msgs[key]))


def main(args: argparse.Namespace):
    logging.basicConfig(level=logging.INFO)

    cli = Client(args.bot_token)

    L.info("checking validity of token...")
    user = cli.auth_test()
    if not user["ok"]:
        raise RuntimeError("token isn't valid")

    L.info("fetching channels...")
    channels = get_channels(cli)

    L.info("fetching users...")
    users = get_users(cli)

    L.info("fetching messages...")
    messages: Dict[str, List[Any]] = {}
    for channel in channels:
        if user["user_id"] in channel["members"]:
            messages[channel["name"]] = get_messages(cli, channel)

    output(args.destination, channels, users, messages, args.download_token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--bot-token", help="token for accesssing Slack")
    parser.add_argument("--download-token", help="token for fetching assets from Slack")
    parser.add_argument("--destination", help="the output directory")

    args: argparse.Namespace = parser.parse_args()

    main(args)

