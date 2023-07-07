from fastapi_websocket_rpc import RpcMethodsBase, WebSocketRpcClient

from robot.errors import RemoteError
from functools import wraps
from robot.api import logger
from robot.utils import (DotDict, is_bytes, is_dict_like, is_list_like,
                         is_number, is_string, safe_str)
from robot.running.context import EXECUTION_CONTEXTS

import re

from ws_common import Binary, RobotSerializingWebSocket


def convertToSync(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        runner = f(*args, **kwargs)

        context = EXECUTION_CONTEXTS.current
        if context is not None:
            if context.asynchronous.is_loop_required(runner):
                loop = context.asynchronous.event_loop

                if loop.is_running():
                    return loop.create_task(runner)
                else:
                    return loop.run_until_complete(runner)
        else:
            raise Exception("Context not available")
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
        client = WebSocketRpcClient(uri, 
                                    RpcMethodsBase(),
                                    serializing_socket_cls=RobotSerializingWebSocket)
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
        coercer = ArgumentCoercer()
        args = coercer.coerce(args)
        kwargs = coercer.coerce(kwargs)
        rpcResult = await self._client.other.run_keyword(name=name,
                                                         args=args,
                                                         kwargs=kwargs)
        resultDict = rpcResult.result
        result = RemoteResult(resultDict)
        if result.status != 'PASS':
            raise RemoteError(result.error, result.traceback, result.fatal,
                              result.continuable)
        return result.return_


class ArgumentCoercer:
    binary = re.compile('[\x00-\x08\x0B\x0C\x0E-\x1F]')
    non_ascii = re.compile('[\x80-\xff]')

    def coerce(self, argument):
        for handles, handler in [(is_string, self._handle_string),
                                 (is_bytes, self._handle_bytes),
                                 (is_number, self._pass_through),
                                 (is_dict_like, self._coerce_dict),
                                 (is_list_like, self._coerce_list),
                                 (lambda arg: True, self._to_string)]:
            if handles(argument):
                return handler(argument)

    def _handle_string(self, arg):
        if self._string_contains_binary(arg):
            return self._handle_binary_in_string(arg)
        return arg

    def _string_contains_binary(self, arg):
        return (self.binary.search(arg) or
                is_bytes(arg) and self.non_ascii.search(arg))

    def _handle_binary_in_string(self, arg):
        try:
            if not is_bytes(arg):
                # Map Unicode code points to bytes directly
                arg = arg.encode('latin-1')
        except UnicodeError:
            raise ValueError('Cannot represent %r as binary.' % arg)
        return Binary(arg)

    def _handle_bytes(self, arg):
        return Binary(arg)

    def _pass_through(self, arg):
        return arg

    def _coerce_list(self, arg):
        return [self.coerce(item) for item in arg]

    def _coerce_dict(self, arg):
        return dict((self._to_key(key), self.coerce(arg[key])) for key in arg)

    def _to_key(self, item):
        item = self._to_string(item)
        self._validate_key(item)
        return item

    def _to_string(self, item):
        item = safe_str(item) if item is not None else ''
        return self._handle_string(item)

    def _validate_key(self, key):
        if isinstance(key, Binary):
            raise ValueError('Dictionary keys cannot be binary. Got %r.' % (key.data,))


class RemoteResult:

    def __init__(self, result):
        if not (is_dict_like(result) and 'status' in result):
            raise RuntimeError('Invalid remote result dictionary: %s' % result)
        self.status = result['status']
        self.output = safe_str(self._get(result, 'output'))
        self.return_ = self._get(result, 'return')
        self.error = safe_str(self._get(result, 'error'))
        self.traceback = safe_str(self._get(result, 'traceback'))
        self.fatal = bool(self._get(result, 'fatal', False))
        self.continuable = bool(self._get(result, 'continuable', False))

    def _get(self, result, key, default=''):
        value = result.get(key, default)
        return self._convert(value)

    def _convert(self, value):
        if isinstance(value, Binary):
            return bytes(value.data)
        if is_dict_like(value):
            return DotDict((k, self._convert(v)) for k, v in value.items())
        if is_list_like(value):
            return [self._convert(v) for v in value]
        return value

