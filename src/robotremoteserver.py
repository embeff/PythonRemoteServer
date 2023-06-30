#  Copyright 2008-2015 Nokia Networks
#  Copyright 2016- Robot Framework Foundation
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from __future__ import print_function

import inspect
import os
import re
import signal
import sys
import traceback

from fastapi import FastAPI
from fastapi_websocket_rpc import RpcMethodsBase, WebsocketRPCEndpoint
import uvicorn
import base64
import pickle
from functools import partial
import asyncio
from collections.abc import Iterator

if sys.version_info < (3,):
    from StringIO import StringIO
    from xmlrpclib import Binary, ServerProxy
    from collections import Mapping
    PY2, PY3 = True, False

    def getfullargspec(func):
        return inspect.getargspec(func) + ([], None, {})
else:
    from inspect import getfullargspec
    from io import StringIO
    from xmlrpc.client import Binary, ServerProxy
    from collections.abc import Mapping
    PY2, PY3 = False, True
    unicode = str
    long = int


__all__ = ['RobotRemoteServer', 'stop_remote_server', 'test_remote_server']
__version__ = '1.1.1'

BINARY = re.compile('[\x00-\x08\x0B\x0C\x0E-\x1F]')
NON_ASCII = re.compile('[\x80-\xff]')


class RobotRemoteServer(object):

    class RemoteCalls(RpcMethodsBase):
        def __init__(self, lib):
            self.lib = lib

        async def get_keyword_names(self) -> list:
            return self.lib.get_keyword_names() + ["stop_remote_server"]

        async def get_keyword_arguments(self, name):
            if name == 'stop_remote_server':
                return []
            return self.lib.get_keyword_arguments(name)

        async def get_keyword_documentation(self, name):
            if name == 'stop_remote_server':
                return ('Stop the remote server unless stopping is \
                        disabled.\n\n' 'Return ``True/False`` depending \
                            was server stopped or not.')
            return self.lib.get_keyword_documentation(name)

        async def get_keyword_tags(self, name):
            if name == 'stop_remote_server':
                return []
            return self.lib.get_keyword_tags(name)

        async def get_keyword_types(self, name):
            pass

        async def run_keyword(self, name="", sArgs=None, sKwargs=None) -> dict:
            args = pickle.loads(base64.b64decode(sArgs))
            kwargs = pickle.loads(base64.b64decode(sKwargs))
            print(f"Calling lib.run_keyword with {args} and {kwargs}")

            if name == 'stop_remote_server':
                return KeywordRunner(self.stop_remote_server)\
                    .run_keyword(args, kwargs)

            try:
                result = await self.lib.run_keyword(name, args, kwargs)
            except Exception as e:
                print(f"Exception occured while running a keyword: \
                      {e} {traceback.extract_tb(e.__traceback__)}")
            return result

    def __init__(self, library, host='0.0.0.0', port=9000, port_file=None,
                 allow_stop='DEPRECATED', serve=True, allow_remote_stop=True):
        """Configure and start-up remote server.

        :param library:     Test library instance or module to host.
        :param host:        Address to listen. Use ``'0.0.0.0'`` to listen
                            to all available interfaces.
        :param port:        Port to listen. Use ``0`` to select a free port
                            automatically. Can be given as an integer or as
                            a string.
        :param port_file:   File to write the port that is used. ``None`` means
                            no such file is written. Port file is created after
                            the server is started and removed automatically
                            after it has stopped.
        :param allow_stop:  DEPRECATED since version 1.1. Use
                            ``allow_remote_stop`` instead.
        :param serve:       If ``True``, start the server automatically and
                            wait for it to be stopped.
        :param allow_remote_stop:  Allow/disallow stopping the server using
                            ``Stop Remote Server`` keyword and
                            ``stop_remote_server`` XML-RPC method.
        """
        self._library = RemoteLibraryFactory(library)
        self._app = FastAPI()
        self._endpoint = \
            WebsocketRPCEndpoint(self.RemoteCalls(self._library),
                                 on_disconnect=[self.on_disconnect],
                                 on_connect=[self.on_connect])
        self._endpoint.register_route(self._app, "/ws")
        self._host = host
        self._port = port if isinstance(port, int) else int(port)
        print(f"Port: {self._port} is {self._port.__class__.__name__}")
        self._port_file = port_file

        if serve:
            self.serve()

    async def on_connect(self, channel):
        print(f"Client connected on channel {channel.id}")

    async def on_disconnect(self, channel):
        print(f"Client disconnected from channel {channel.id}")

    @property
    def server_address(self):
        """Server address as a tuple ``(host, port)``."""
        return (self._host, self._port)

    @property
    def server_port(self):
        """Server port as an integer."""
        return self._port

    def serve(self, log=True):
        """Start the server and wait for it to be stopped.

        :param log:  When ``True``, print messages about start and stop to
                     the console.

        Automatically activates the server if it is not activated already.

        If this method is executed in the main thread, automatically registers
        signals SIGINT, SIGTERM and SIGHUP to stop the server.

        Using this method requires using ``serve=False`` when initializing the
        server. Using ``serve=True`` is equal to first using ``serve=False``
        and then calling this method.

        In addition to signals, the server can be stopped with the ``Stop
        Remote Server`` keyword and the ``stop_remote_serve`` XML-RPC method,
        unless they are disabled when the server is initialized. If this method
        is executed in a thread, then it is also possible to stop the server
        using the :meth:`stop` method.
        """

        self._announce_start(log, self._port_file)
        print("Starting Uvicorn")
        uvicorn.run(self._app, host=self._host, port=self._port)
        self._announce_stop(log, self._port_file)

    def _announce_start(self, log, port_file):
        self._log('started', log)
        if port_file:
            with open(port_file, 'w') as pf:
                pf.write(str(self.server_port))

    def _announce_stop(self, log, port_file):
        self._log('stopped', log)
        if port_file and os.path.exists(port_file):
            os.remove(port_file)

    def _log(self, action, log=True, warn=False):
        log = False
        if log:
            address = f"{self.server_address[0]}:{self.server_address[1]}"
            if warn:
                print('*WARN*', end=' ')
            print(f"Robot Framework remote server at {address} {action}.")

    def stop(self):
        """Stop server."""
        self._log("Method 'stop' not implemented!", warn=True)

    def stop_remote_server(self, log=True):
        self.stop()
        return True


class SignalHandler(object):

    def __init__(self, handler):
        self._handler = lambda signum, frame: handler()
        self._original = {}

    def __enter__(self):
        for name in 'SIGINT', 'SIGTERM', 'SIGHUP':
            if hasattr(signal, name):
                try:
                    orig = signal.signal(getattr(signal, name), self._handler)
                except ValueError:  # Not in main thread
                    return
                self._original[name] = orig

    def __exit__(self, *exc_info):
        while self._original:
            name, handler = self._original.popitem()
            signal.signal(getattr(signal, name), handler)


def RemoteLibraryFactory(library):
    if inspect.ismodule(library):
        return StaticRemoteLibrary(library)
    get_keyword_names = dynamic_method(library, 'get_keyword_names')
    if not get_keyword_names:
        return StaticRemoteLibrary(library)
    run_keyword = dynamic_method(library, 'run_keyword')
    if not run_keyword:
        return HybridRemoteLibrary(library, get_keyword_names)
    return DynamicRemoteLibrary(library, get_keyword_names, run_keyword)


def dynamic_method(library, underscore_name):
    tokens = underscore_name.split('_')
    camelcase_name = tokens[0] + ''.join(t.title() for t in tokens[1:])
    for name in underscore_name, camelcase_name:
        method = getattr(library, name, None)
        if method and is_function_or_method(method):
            return method
    return None


def is_function_or_method(item):
    return inspect.isfunction(item) or inspect.ismethod(item)


class StaticRemoteLibrary(object):

    def __init__(self, library):
        self._library = library
        self._names, self._robot_name_index = self._get_keyword_names(library)

    def _get_keyword_names(self, library):
        names = []
        robot_name_index = {}
        for name, kw in inspect.getmembers(library):
            if is_function_or_method(kw):
                if getattr(kw, 'robot_name', None):
                    names.append(kw.robot_name)
                    robot_name_index[kw.robot_name] = name
                elif name[0] != '_':
                    names.append(name)
        return names, robot_name_index

    def get_keyword_names(self):
        return self._names

    async def run_keyword(self, name, args, kwargs=None):
        kw = self._get_keyword(name)
        return await KeywordRunner(kw).run_keyword(args, kwargs)

    def _get_keyword(self, name):
        if name in self._robot_name_index:
            name = self._robot_name_index[name]
        return getattr(self._library, name)

    def get_keyword_arguments(self, name):
        if __name__ == '__init__':
            return []
        kw = self._get_keyword(name)
        args, varargs, kwargs, defaults, _, _, _ = getfullargspec(kw)
        if inspect.ismethod(kw):
            args = args[1:]  # drop 'self'
        if defaults:
            args, names = args[:-len(defaults)], args[-len(defaults):]
            args += [f"{n}={d}" for n, d in zip(names, defaults)]
        if varargs:
            args.append(f"*{varargs}")
        if kwargs:
            args.append(f"**{kwargs}")
        return args

    def get_keyword_documentation(self, name):
        if name == '__intro__':
            source = self._library
        elif name == '__init__':
            source = self._get_init(self._library)
        else:
            source = self._get_keyword(name)
        return inspect.getdoc(source) or ''

    def _get_init(self, library):
        if inspect.ismodule(library):
            return None
        init = getattr(library, '__init__', None)
        return init if self._is_valid_init(init) else None

    def _is_valid_init(self, init):
        if not init:
            return False
        # https://bitbucket.org/pypy/pypy/issues/2462/
        if 'PyPy' in sys.version:
            if PY2:
                return init.__func__ is not object.__init__.__func__
            return init is not object.__init__
        return is_function_or_method(init)

    def get_keyword_tags(self, name):
        keyword = self._get_keyword(name)
        return getattr(keyword, 'robot_tags', [])


class HybridRemoteLibrary(StaticRemoteLibrary):

    def __init__(self, library, get_keyword_names):
        StaticRemoteLibrary.__init__(self, library)
        self.get_keyword_names = get_keyword_names


class DynamicRemoteLibrary(HybridRemoteLibrary):

    def __init__(self, library, get_keyword_names, run_keyword):
        HybridRemoteLibrary.__init__(self, library, get_keyword_names)
        self._run_keyword = run_keyword
        self._supports_kwargs = self._get_kwargs_support(run_keyword)
        self._get_keyword_arguments \
            = dynamic_method(library, 'get_keyword_arguments')
        self._get_keyword_documentation \
            = dynamic_method(library, 'get_keyword_documentation')
        self._get_keyword_tags \
            = dynamic_method(library, 'get_keyword_tags')

    def _get_kwargs_support(self, run_keyword):
        args = getfullargspec(run_keyword)[0]
        return len(args) > 3    # self, name, args, kwargs=None

    async def run_keyword(self, name, args, kwargs=None):
        args = [name, args, kwargs] if kwargs else [name, args]
        return await KeywordRunner(self._run_keyword).run_keyword(args)

    def get_keyword_arguments(self, name):
        if self._get_keyword_arguments:
            return self._get_keyword_arguments(name)
        if self._supports_kwargs:
            return ['*varargs', '**kwargs']
        return ['*varargs']

    def get_keyword_documentation(self, name):
        if self._get_keyword_documentation:
            return self._get_keyword_documentation(name)
        return ''

    def get_keyword_tags(self, name):
        if self._get_keyword_tags:
            return self._get_keyword_tags(name)
        return []


class KeywordRunner(object):

    def __init__(self, keyword):
        self._keyword = keyword

    async def run_keyword(self, args, kwargs=None):
        result = KeywordResult()
        with StandardStreamInterceptor() as interceptor:
            try:
                kw = partial(self._keyword, *args,
                             **kwargs if kwargs is not None else {})
                loop = asyncio.get_running_loop()
                return_value = await loop.run_in_executor(None, kw)
            except Exception:
                result.set_error(*sys.exc_info())
            else:
                try:
                    result.set_return(return_value)
                except Exception:
                    result.set_error(*sys.exc_info()[:2])
                else:
                    result.set_status('PASS')
        result.set_output(interceptor.output)
        return result.data

    def _handle_binary(self, arg):
        # No need to compare against other iterables or mappings because we
        # only get actual lists and dicts over XML-RPC. Binary cannot be
        # a dictionary key either.
        if isinstance(arg, list):
            return [self._handle_binary(item) for item in arg]
        if isinstance(arg, dict):
            return dict((key, self._handle_binary(arg[key])) for key in arg)
        if isinstance(arg, Binary):
            return arg.data
        return arg


class StandardStreamInterceptor(object):

    def __init__(self):
        self.output = ''
        self.origout = sys.stdout
        self.origerr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        close = [sys.stdout, sys.stderr]
        sys.stdout = self.origout
        sys.stderr = self.origerr
        for stream in close:
            stream.close()
        if stdout and stderr:
            if not stderr.startswith(('*TRACE*', '*DEBUG*', '*INFO*', '*HTML*',
                                      '*WARN*', '*ERROR*')):
                stderr = f"*INFO* {stderr}"
            if not stdout.endswith('\n'):
                stdout += '\n'
        self.output = stdout + stderr


class KeywordResult(object):
    _generic_exceptions = (AssertionError, RuntimeError, Exception)

    def __init__(self):
        self.data = {'status': 'FAIL'}

    def set_error(self, exc_type, exc_value, exc_tb=None):
        self.data['error'] = \
            self._handle_return_value(self._get_message(exc_type, exc_value))
        if exc_tb:
            self.data['traceback'] = \
                self._handle_return_value(self._get_traceback(exc_tb))
        continuable = self._get_error_attribute(exc_value, 'CONTINUE')
        if continuable:
            self.data['continuable'] = self._handle_return_value(continuable)
        fatal = self._get_error_attribute(exc_value, 'EXIT')
        if fatal:
            self.data['fatal'] = self._handle_return_value(fatal)

    def _get_message(self, exc_type, exc_value):
        name = exc_type.__name__
        message = str(exc_value)
        if not message:
            return name
        if exc_type in self._generic_exceptions \
                or getattr(exc_value, 'ROBOT_SUPPRESS_NAME', False):
            return message
        return f"{name}: {message}"

    def _get_traceback(self, exc_tb):
        # Latest entry originates from this module so it can be removed
        entries = traceback.extract_tb(exc_tb)[1:]
        trace = ''.join(traceback.format_list(entries))
        return 'Traceback (most recent call last):\n' + trace

    def _get_error_attribute(self, exc_value, name):
        return bool(getattr(exc_value, f"ROBOT_{name}_ON_FAILURE", False))

    def set_return(self, value):
        value = self._handle_return_value(value)
        if value is not None and value != '':
            self.data['return'] = value

    def _handle_return_value(self, ret):
        if ret is None:
            return None
        if isinstance(ret, (int, float, bool)):
            return ret
        if isinstance(ret, str):
            return "s" + ret
        if isinstance(ret, bytes):
            return b'b' + base64.b64encode(ret)
        if isinstance(ret, Mapping):
            return dict((str(key), self._handle_return_value(value))
                        for key, value in ret.items())
        if isinstance(ret, Iterator):
            return self._handle_return_value(list(ret))
        try:
            return [self._handle_return_value(item) for item in ret]
        except TypeError:
            return self.str(ret)

    def set_status(self, status):
        self.data['status'] = status

    def set_output(self, output):
        if output:
            self.data['output'] = self._handle_return_value(output)


def test_remote_server(uri, log=True):
    """Test is remote server running.

    :param uri:  Server address.
    :param log:  Log status message or not.
    :return      ``True`` if server is running, ``False`` otherwise.
    """
    logger = print if log else lambda message: None
    try:
        ServerProxy(uri).get_keyword_names()
    except Exception:
        logger(f"No remote server running at {uri}.")
        return False
    logger(f"Remote server running at {uri}.")
    return True


def stop_remote_server(uri, log=True):
    """Stop remote server unless server has disabled stopping.

    :param uri:  Server address.
    :param log:  Log status message or not.
    :return      ``True`` if server was stopped or it was not running in
                 the first place, ``False`` otherwise.
    """
    logger = print if log else lambda message: None
    if not test_remote_server(uri, log=False):
        logger(f"No remote server running at {uri}.")
        return True
    logger(f"Stopping remote server at {uri}.")
    if not ServerProxy(uri).stop_remote_server():
        logger('Stopping not allowed!')
        return False
    return True


if __name__ == '__main__':

    def parse_args(script, *args):
        actions = {'stop': stop_remote_server, 'test': test_remote_server}
        if not (0 < len(args) < 3) or args[0] not in actions:
            sys.exit('Usage:  %s {test|stop} [uri]' % os.path.basename(script))
        uri = args[1] if len(args) == 2 else 'http://127.0.0.1:8270'
        if '://' not in uri:
            uri = 'http://' + uri
        return actions[args[0]], uri

    action, uri = parse_args(*sys.argv)
    success = action(uri)
    sys.exit(0 if success else 1)
