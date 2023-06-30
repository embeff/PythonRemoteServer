from subprocess import Popen, STDOUT, CREATE_NEW_CONSOLE
import os


process = None


def start_remote_library_in_process(library, port, portFile, args, stdoutFile, stderrFile):
    arguments = ["python", library, port, portFile] + args

    stdout = _new_stream(stdoutFile)
    if stderrFile == "STDOUT":
        stderr = STDOUT
    else:
        stderr = _new_stream(stderrFile)

    global process
    process = Popen(stderr=stderr, stdout=stdout, args=arguments, creationflags=CREATE_NEW_CONSOLE)

    return 0


def kill_remote_server_in_process():
    if process is None:
        return
    Popen(["taskkill", "/F", "/PID", str(process.pid)])


def _new_stream(name):
    if name == 'DEVNULL':
        return open(os.devnull, 'w')
    cwd = os.path.abspath('.')
    path = os.path.normpath(os.path.join(cwd, name))
    return open(path, 'w')
