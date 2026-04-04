"""企业微信消息加解密。

基于企业微信官方加解密方案简化实现：
https://developer.work.weixin.qq.com/document/path/90307
"""

import base64
import hashlib
import struct
import xml.etree.ElementTree as ET
from Crypto.Cipher import AES


class WXBizMsgCrypt:
    def __init__(self, token: str, encoding_aes_key: str, corpid: str):
        self.token = token
        self.corpid = corpid
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def _sha1_sign(self, *args: str) -> str:
        items = sorted(args)
        return hashlib.sha1("".join(items).encode("utf-8")).hexdigest()

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        sign = self._sha1_sign(self.token, timestamp, nonce, echostr)
        if sign != msg_signature:
            raise ValueError("签名验证失败")
        return self._decrypt(echostr)

    def decrypt_msg(self, msg_signature: str, timestamp: str, nonce: str, post_data: str) -> str:
        root = ET.fromstring(post_data)
        encrypt = root.find("Encrypt").text
        sign = self._sha1_sign(self.token, timestamp, nonce, encrypt)
        if sign != msg_signature:
            raise ValueError("签名验证失败")
        return self._decrypt(encrypt)

    def _pad(self, data: bytes) -> bytes:
        block_size = 32
        padding = block_size - (len(data) % block_size)
        return data + bytes([padding] * padding)

    def _unpad(self, data: bytes) -> bytes:
        padding = data[-1]
        return data[:-padding]

    def _decrypt(self, encrypted: str) -> str:
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        decrypted = cipher.decrypt(base64.b64decode(encrypted))
        decrypted = self._unpad(decrypted)
        msg_len = struct.unpack("!I", decrypted[16:20])[0]
        content = decrypted[20:20 + msg_len].decode("utf-8")
        from_corpid = decrypted[20 + msg_len:].decode("utf-8")
        if from_corpid != self.corpid:
            raise ValueError(f"corpid 不匹配: {from_corpid} != {self.corpid}")
        return content


def parse_wx_msg(xml_str: str) -> dict:
    root = ET.fromstring(xml_str)
    return {
        "to_user": root.findtext("ToUserName", ""),
        "from_user": root.findtext("FromUserName", ""),
        "create_time": root.findtext("CreateTime", ""),
        "msg_type": root.findtext("MsgType", ""),
        "content": root.findtext("Content", ""),
        "msg_id": root.findtext("MsgId", ""),
        "agent_id": root.findtext("AgentID", ""),
        "event": root.findtext("Event", ""),
        "token": root.findtext("Token", ""),
    }
