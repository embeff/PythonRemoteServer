from fastapi_websocket_rpc.simplewebsocket import SimpleWebSocket
import base64
import json


class Binary:
    """Wrapper for binary data."""

    def __init__(self, data=None):
        if data is None:
            data = b""
        else:
            if not isinstance(data, (bytes, bytearray)):
                raise TypeError("expected bytes or bytearray, not %s" %
                                data.__class__.__name__)
            data = bytes(data)  # Make a copy of the bytes!
        self.data = data

    ##
    # Get buffer contents.
    #
    # @return Buffer contents, as an 8-bit string.

    def __str__(self):
        return str(self.data, "latin-1")  # XXX encoding?!

    def __eq__(self, other):
        if isinstance(other, Binary):
            other = other.data
        return self.data == other

    @staticmethod
    def fromJSON(data):
        if data['__type__'] == "Binary":
            return base64.b64decode(data['value'])
        return data

    def toJSON(self):
        encoded = base64.b64encode(self.data).decode('ascii')
        return {"__type__": "Binary", "value": encoded}


def robotTypesObjectHook(dct):
    if '__type__' in dct:
        if dct['__type__'] == "Binary":
            return Binary.fromJSON(dct)
    return dct


class RobotJsonEncoder(json.JSONEncoder):
    def default(self, z):
        if isinstance(z, Binary):
            return z.toJSON()
        if isinstance(z, (bytes, bytearray)):
            return Binary(z).toJSON()
        return super().default(z)


class RobotSerializingWebSocket(SimpleWebSocket):
    def __init__(self, websocket: SimpleWebSocket):
        self._websocket = websocket
        self.encoder = RobotJsonEncoder()

    def _serialize(self, msg):
        return msg.json(encoder=self.encoder.default)

    def _deserialize(self, buffer):
        return json.loads(buffer, object_hook=robotTypesObjectHook)

    async def send(self, msg):
        await self._websocket.send(self._serialize(msg))

    async def recv(self):
        msg = await self._websocket.recv()

        return self._deserialize(msg)

    async def close(self, code: int = 1000):
        await self._websocket.close(code)
