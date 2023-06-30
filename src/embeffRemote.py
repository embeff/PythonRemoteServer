import asyncio
from fastapi_websocket_rpc import RpcMethodsBase, WebSocketRpcClient
import pickle
import base64
from collections.abc import Mapping
from unicodedata import normalize
from collections.abc import Iterable
from collections import OrderedDict
from robot.errors import RemoteError
from functools import wraps
from robot.api import logger


def convertToSync(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.get_event_loop().run_until_complete(f(*args, **kwargs))
    return wrapper


class embeffRemote(object):
    ROBOT_LIBRARY_SCOPE = 'TEST SUITE'

    def __init__(self, uri, timeout=None):
        self._client = self.createClient(uri)

    def __del__(self):
        if self._client is not None:
            try:
                self.exitClient()
            except Exception as e:
                logger.console(f"Exception occured while deconstructing\
                               Remote Client: {e}")

    @convertToSync
    async def createClient(self, uri):
        client = WebSocketRpcClient(uri, RpcMethodsBase())
        result = await client.__aenter__()
        return result

    @convertToSync
    async def exitClient(self):
        await self._client.__aexit__()

    @convertToSync
    async def get_keyword_names(self):
        response = await self._client.other.get_keyword_names()
        return response.result

    def get_keyword_arguments(self, name):
        return None

    def get_keyword_types(self, name):
        return None

    def get_keyword_tags(self, name):
        return None

    def get_keyword_documentation(self, name):
        return None

    @convertToSync
    async def run_keyword(self, name, args, kwargs):
        pArgs = pickle.dumps(args)
        pKwargs = pickle.dumps(kwargs)
        sArgs = base64.b64encode(pArgs)
        sKwargs = base64.b64encode(pKwargs)
        rpcResult = await self._client.other.run_keyword(name=name,
                                                         sArgs=sArgs,
                                                         sKwargs=sKwargs)
        resultDict = rpcResult.result
        result = RemoteResult(resultDict)
        if result.status != 'PASS':
            raise RemoteError(result.error, result.traceback, result.fatal,
                              result.continuable)
        return result.return_


class RemoteResult(object):

    def __init__(self, result):
        logger
        logger.console(f"Received: {result}")
        if not (isinstance(result, Mapping) and 'status' in result):
            raise RuntimeError(f'Invalid remote result dictionary: \
                               {result.__class__.__name__}')
        self.status = result['status']
        self.output = unic(self._get(result, 'output'))
        self.return_ = self._get(result, 'return')
        self.error = unic(self._get(result, 'error'))
        self.traceback = unic(self._get(result, 'traceback'))
        self.fatal = bool(self._get(result, 'fatal', False))
        self.continuable = bool(self._get(result, 'continuable', False))

    def _get(self, result, key, default=''):
        value = result.get(key, default)
        return self._convert(value)

    def _convert(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, str):
            return self._convertString(value)
        if isinstance(value, Mapping):
            return DotDict((k, self._convert(v)) for k, v in value.items())
        if is_list_like(value):
            return [self._convert(v) for v in value]
        return value

    def _convertString(self, value):
        if len(value) == 0:
            return ''
        if value[0] == "s":
            return value[1:]
        elif value[0] == "b":
            return base64.b64decode(value[1:])
        else:
            logger.console(f"Got wrong byte/string format: {value}")
            raise ValueError


def is_list_like(item):
    if isinstance(item, (str, bytes, bytearray)):
        return False
    return isinstance(item, Iterable)


def unic(item):
    item = _unic(item)
    try:
        return normalize('NFC', item)
    except ValueError:
        # https://github.com/IronLanguages/ironpython2/issues/628
        return item


def _unic(item):
    if isinstance(item, str):
        return item
    if isinstance(item, (bytes, bytearray)):
        try:
            return item.decode('ASCII')
        except UnicodeError:
            return ''.join(chr(b) if b < 128 else '\\x%x' % b for b in item)
    try:
        return str(item)
    except Exception:
        return _unrepresentable_object(item)


def _unrepresentable_object(item):
    return None


class DotDict(OrderedDict):

    def __init__(self, *args, **kwds):
        args = [self._convert_nested_initial_dicts(a) for a in args]
        kwds = self._convert_nested_initial_dicts(kwds)
        OrderedDict.__init__(self, *args, **kwds)

    def _convert_nested_initial_dicts(self, value):
        items = value.items() if isinstance(value, Mapping) else value
        return OrderedDict((key, self._convert_nested_dicts(value))
                           for key, value in items)

    def _convert_nested_dicts(self, value):
        if isinstance(value, DotDict):
            return value
        if isinstance(value, Mapping):
            return DotDict(value)
        if isinstance(value, list):
            value[:] = [self._convert_nested_dicts(item) for item in value]
        return value

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        if not key.startswith('_OrderedDict__'):
            self[key] = value
        else:
            OrderedDict.__setattr__(self, key, value)

    def __delattr__(self, key):
        try:
            self.pop(key)
        except KeyError:
            OrderedDict.__delattr__(self, key)

    def __eq__(self, other):
        return dict.__eq__(self, other)

    def __ne__(self, other):
        return not self == other

    def __str__(self):
        return '{%s}' % ', '.join('%r: %r' % (key, self[key]) for key in self)

    # Must use original dict.__repr__ to allow customising PrettyPrinter.
    __repr__ = dict.__repr__
