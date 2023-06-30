*** Settings ***
Library              OperatingSystem
Library              Process
Library              Collections
Library              resource.py

*** Variables ***
${INTERPRETER}       python
${SERVER TIMEOUT}    30 seconds

*** Keywords ***
Start And Import Remote Library
    [Arguments]    ${library}    ${name}=Remote    @{args}
    Set Pythonpath
    ${port} =    Start Remote Server    ${library}    args=${args}
    Set Suite Variable    ${ACTIVE PORT}    ${port}
    Set Log Level    DEBUG
    Import Client

Start Remote Server
    [Arguments]    ${library}    ${port}=9000    ${args}=@{EMPTY}
    @{interpreter} =    Split Command Line    ${INTERPRETER}
    ${library} =        Normalize Path        ${CURDIR}/../libs/${library}
    ${port file} =      Normalize Path        ${CURDIR}/../results/server_port.txt
    ${output} =         Normalize Path        ${CURDIR}/../results/server_output.txt

    ${process} =    Start Remote Library In Process    ${library}    ${port}    ${port file}    args=@{args}    stdoutFile=${output}    stderrFile=STDOUT

    TRY
        Wait Until Created    ${port file}    timeout=${SERVER TIMEOUT}
    EXCEPT
        Fail    Starting remote server failed!
    END
    ${port} =    Get File    ${port file}
    RETURN    ${port}

Import Client
    Import Library    ${CURDIR}/../../src/embeffRemote.py    ws://localhost:9000/ws

Set Pythonpath
    ${src} =    Normalize Path    ${CURDIR}/../../src
    Set Environment Variable    PYTHONPATH    ${src}
    Set Environment Variable    JYTHONPATH    ${src}
    Set Environment Variable    IRONPYTHONPATH    ${src}

Stop Remote Library
    [Arguments]    ${test logging}=True
    Stop Remote Server In Process

Server Should Be Stopped And Correct Messages Logged
    [Arguments]    ${test logging}=True
    ${result} =    Wait For Process    timeout=10s    on_timeout=terminate
    ${expected} =    Catenate    SEPARATOR=\n
    ...    Robot Framework remote server at 127.0.0.1:${ACTIVE PORT} started.
    ...    Robot Framework remote server at 127.0.0.1:${ACTIVE PORT} stopped.
    IF    ${test logging}
        Should Be Equal    ${result.stdout}    ${expected}
    END
    Should Be Equal    ${result.rc}    ${0}
