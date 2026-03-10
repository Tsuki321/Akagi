# MajsoulMax update_liqi.py — auto-update liqi proto files.
# Ported from https://github.com/Avenshy/MajsoulMax/blob/main/plugin/update_liqi.py
# Key change: proto directory now resolves relative to this file's location
# (akagi_ng/majsoulmax/proto/).
import hashlib
import os
from pathlib import Path

import requests
from loguru import logger

LIQI_FILES = ("liqi.json", "liqi.proto", "liqi_pb2.py")

# Proto directory is akagi_ng/majsoulmax/proto/ (sibling to this file)
PROTO_DIR = Path(__file__).resolve().parent / "proto"


def get_version():
    req = requests.get("https://game.maj-soul.com/1/version.json", timeout=10)
    return req.json()["version"]


def get_prefix(version):
    req = requests.get(
        f"https://game.maj-soul.com/1/resversion{version}.json", timeout=10
    )
    return req.json()["res"]["res/proto/liqi.json"]["prefix"]


def _auth_headers(token: str):
    headers = {"X-GitHub-Api-Version": "2022-11-28"}
    if token != "":
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _calculate_hash(blobs: dict) -> str:
    hasher = hashlib.sha256()
    for name in LIQI_FILES:
        hasher.update(blobs[name])
    return hasher.hexdigest()


def _read_local_hash():
    blobs = {}
    for name in LIQI_FILES:
        path = PROTO_DIR / name
        with open(path, "rb") as f:
            blobs[name] = f.read()
    return _calculate_hash(blobs)


def _download_latest_release(token: str):
    req = requests.get(
        "https://api.github.com/repos/Avenshy/AutoLiqi/releases/latest",
        timeout=10,
        headers=_auth_headers(token),
    )
    return req


def _download_liqi_assets(release: dict, token: str):
    assets = {
        item["name"]: item
        for item in release.get("assets", [])
        if item["name"] in LIQI_FILES
    }
    if len(assets) != len(LIQI_FILES):
        missing = {name for name in LIQI_FILES if name not in assets}
        raise FileNotFoundError(f"发布页缺少文件: {missing}")

    blobs = {}
    for name in LIQI_FILES:
        item = assets[name]
        logger.warning(f"下载 {name} 中……")
        req = requests.get(
            item["browser_download_url"], timeout=10, headers=_auth_headers(token)
        )
        blobs[name] = req.content
        logger.success(f"下载 {name} 成功！")
    return blobs


def update(version: str, token: str, stored_hash: str = "") -> dict:
    """Update liqi proto files. Returns dict with 'version' and 'hash' keys."""
    new_version = "v" + get_version()
    local_hash = None
    try:
        local_hash = _read_local_hash()
    except FileNotFoundError:
        local_hash = None
    except OSError as exc:
        logger.error(f"读取本地liqi文件失败：{exc}")
        local_hash = None

    stored_hash = stored_hash or ""
    if version == new_version and stored_hash != "" and local_hash == stored_hash:
        logger.success(f"liqi文件无需更新，当前版本：{new_version}")
        return {"version": new_version, "hash": local_hash}

    req = _download_latest_release(token)
    if req.headers.get("X-RateLimit-Remaining") == "0":
        logger.error(
            "github api额度用完，无法更新liqi文件！请尝试以下方法：\n"
            "1. 在 Akagi 设置中填入你的Github Token后重试\n"
            "2. 在 https://github.com/Avenshy/AutoLiqi/releases/latest 手动下载"
            "liqi.json、liqi.proto、liqi_pb2.py，"
            "放入 akagi_ng/majsoulmax/proto/ 中，覆盖同名文件\n"
            "3. 使用或更换代理\n"
            "4. 等待1个小时后再试"
        )
        return {"version": version, "hash": local_hash or stored_hash}

    liqi = req.json()
    if liqi["tag_name"][: len(new_version)] != new_version:
        logger.error("liqi文件需要更新，但AutoLiqi项目还未更新，晚点再来试试吧！")
        logger.error("详细信息请看 https://github.com/Avenshy/AutoLiqi")
        return {"version": version, "hash": local_hash or stored_hash}

    blobs = _download_liqi_assets(liqi, token)
    remote_hash = _calculate_hash(blobs)
    if local_hash == remote_hash:
        logger.success(f"liqi文件无需更新，当前版本：{new_version}")
        return {"version": new_version, "hash": remote_hash}

    PROTO_DIR.mkdir(parents=True, exist_ok=True)
    for name in LIQI_FILES:
        with open(PROTO_DIR / name, "wb") as f:
            f.write(blobs[name])
    logger.success(f"liqi文件更新成功：{new_version}")
    return {"version": new_version, "hash": remote_hash}
