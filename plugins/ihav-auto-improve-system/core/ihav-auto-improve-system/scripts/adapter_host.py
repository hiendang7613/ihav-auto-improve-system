#!/usr/bin/env python3
"""Run one adapter method in the project's own Python and write its JSON result to a file.

    adapter_host.py <project> <adapter.py> <request.json> <response.json>

The core starts one host per call with the interpreter given by --python, so the adapter can import the
project's dependencies and every call gets a fresh process with the run's frozen profile. This file must not
import the core package: it runs under the project's interpreter.
"""

import importlib.util
import json
import sys
import traceback


def main(project, adapter_path, request_path, response_path):
    sys.path[0] = project  # the project's modules come first; this script's folder must not shadow them
    sys.dont_write_bytecode = True  # leave no __pycache__ in the pipeline folder
    with open(request_path, encoding="utf-8") as handle:
        request = json.load(handle)
    try:
        spec = importlib.util.spec_from_file_location("ihav_project_adapter", adapter_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        reply = json.dumps({"ok": True, "result": getattr(module, request["method"])(*request["args"])},
                           ensure_ascii=False)
    except BaseException as exc:  # SystemExit from project code is a failure too, and must be reported
        reply = json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc),
                                                   "traceback": traceback.format_exc()}}, ensure_ascii=False)
    with open(response_path, "w", encoding="utf-8") as handle:
        handle.write(reply)


if __name__ == "__main__":
    main(*sys.argv[1:5])
