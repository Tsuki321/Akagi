# MajsoulMax liqi_new.py — WebSocket message parser for the MajsoulMax mod.
# Ported from https://github.com/Avenshy/MajsoulMax/blob/main/liqi_new.py
# Key change: liqi.json path now uses Akagi's get_assets_dir(); proto imports
# use the akagi_ng.majsoulmax.proto sub-package.
import base64
import json
from enum import Enum
from struct import unpack
from typing import Dict, List

from google.protobuf.json_format import MessageToDict


class MsgType(Enum):
    Notify = 1
    Req = 2
    Res = 3


class LiqiProto:
    def __init__(self):
        # Lazy import: proto.liqi_pb2 is downloaded at runtime.
        from akagi_ng.majsoulmax.proto import basic_pb2 as _basic_pb2
        from akagi_ng.majsoulmax.proto import liqi_pb2 as _liqi_pb2

        self._liqi_pb2 = _liqi_pb2
        self._basic_pb2 = _basic_pb2

        self.tot = 0
        self.res_type = {}
        # Use Akagi's assets dir for liqi.json (same protocol definition)
        from akagi_ng.core.paths import get_assets_dir

        self.jsonProto = json.load(open(get_assets_dir() / "liqi.json", "r", encoding="utf-8"))

    def parse(self, flow_msg):
        liqi_pb2 = self._liqi_pb2
        basic_pb2 = self._basic_pb2

        buf = flow_msg.content
        from_client = flow_msg.from_client
        result = {}
        msg_block = basic_pb2.BaseMessage()
        msg_type = MsgType(buf[0])
        if msg_type == MsgType.Notify:
            msg_block.ParseFromString(buf[1:])
            method_name = msg_block.method_name
            _, lq, message_name = method_name.split(".")
            liqi_pb2_notify = getattr(liqi_pb2, message_name)
            proto_obj = liqi_pb2_notify.FromString(msg_block.data)
            dict_obj = MessageToDict(
                proto_obj, preserving_proto_field_name=True, including_default_value_fields=True
            )
            if "data" in dict_obj:
                B = base64.b64decode(dict_obj["data"])
                action_proto_obj = getattr(liqi_pb2, dict_obj["name"]).FromString(_decode(B))
                action_dict_obj = MessageToDict(
                    action_proto_obj, preserving_proto_field_name=True, including_default_value_fields=True
                )
                dict_obj["data"] = action_dict_obj
            msg_id = self.tot
        else:
            msg_id = unpack("<H", buf[1:3])[0]
            msg_block.ParseFromString(buf[3:])
            if msg_type == MsgType.Req:
                assert msg_id < 1 << 16
                assert msg_id not in self.res_type
                method_name = msg_block.method_name
                _, lq, service, rpc = method_name.split(".")
                proto_domain = self.jsonProto["nested"][lq]["nested"][service]["methods"][rpc]
                liqi_pb2_req = getattr(liqi_pb2, proto_domain["requestType"])
                proto_obj = liqi_pb2_req.FromString(msg_block.data)
                dict_obj = MessageToDict(
                    proto_obj, preserving_proto_field_name=True, including_default_value_fields=True
                )
                self.res_type[msg_id] = (method_name, getattr(liqi_pb2, proto_domain["responseType"]))
            elif msg_type == MsgType.Res:
                assert len(msg_block.method_name) == 0
                assert msg_id in self.res_type
                method_name, liqi_pb2_res = self.res_type.pop(msg_id)
                proto_obj = liqi_pb2_res.FromString(msg_block.data)
                dict_obj = MessageToDict(
                    proto_obj, preserving_proto_field_name=True, including_default_value_fields=True
                )
        result = {"id": msg_id, "type": msg_type, "method": method_name, "data": dict_obj}
        self.tot += 1
        return result


def fromProtobuf(buf: bytes) -> List[Dict]:
    """Dump the struct of protobuf, for observing message structure."""
    p = 0
    result = []
    while p < len(buf):
        block_begin = p
        block_type = buf[p] & 7
        block_id = buf[p] >> 3
        p += 1
        if block_type == 0:
            block_type = "varint"
            data, p = _parseVarint(buf, p)
        elif block_type == 2:
            block_type = "string"
            s_len, p = _parseVarint(buf, p)
            data = buf[p : p + s_len]
            p += s_len
        else:
            raise Exception("unknow type:", block_type, " at", p)
        result.append({"id": block_id, "type": block_type, "data": data, "begin": block_begin})
    return result


def _toVarint(x: int) -> bytes:
    data = 0
    base = 0
    length = 0
    if x == 0:
        return b"\x00"
    while x > 0:
        length += 1
        data += (x & 127) << base
        x >>= 7
        if x > 0:
            data += 1 << (base + 7)
        base += 8
    return data.to_bytes(length, "little")


def toProtobuf(data: List[Dict]) -> bytes:
    """Inverse operation of 'fromProtobuf'."""
    result = b""
    for d in data:
        if d["type"] == "varint":
            result += ((d["id"] << 3) + 0).to_bytes(length=1, byteorder="little")
            result += _toVarint(d["data"])
        elif d["type"] == "string":
            result += ((d["id"] << 3) + 2).to_bytes(length=1, byteorder="little")
            result += _toVarint(len(d["data"]))
            result += d["data"]
        else:
            raise NotImplementedError
    return result


def _parseVarint(buf: bytes, p: int):
    data = 0
    base = 0
    while p < len(buf):
        data += (buf[p] & 127) << base
        base += 7
        p += 1
        if buf[p - 1] >> 7 == 0:
            break
    return (data, p)


def _decode(data: bytes) -> bytes:
    keys = [0x84, 0x5E, 0x4E, 0x42, 0x39, 0xA2, 0x1F, 0x60, 0x1C]
    data = bytearray(data)
    k = len(keys)
    d = len(data)
    for i, j in enumerate(data):
        u = (23 ^ d) + 5 * i + keys[i % k] & 255
        data[i] ^= u
    return bytes(data)
