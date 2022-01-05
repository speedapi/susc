from io import TextIOWrapper
from watchgod import awatch
import asyncio
import time, shutil, pathlib
from os import system, remove
from os.path import abspath, join
from tempfile import TemporaryDirectory

import susc
from . import log

def gen_ts(file: TextIOWrapper):
    # we just need the path
    file.close()
    base = abspath(file.name)
    root = susc.SusFile(base)
    out_root = TemporaryDirectory()
    log.verbose(f"Temp dir: {out_root.name}")

    def recompile():
        start = time.time()

        # run susc
        log.info("Recompiling")
        root = susc.SusFile(base)
        try:
            root.parse()
        except susc.exceptions.SusError as ex:
            log.error(str(ex))
            return
        root.write_output("ts", out_root.name)

        # copy the file over
        shutil.copy(join(out_root.name, "index.ts"), f"{file.name}.ts")

        end = time.time()
        log.done(f"Recompiled in {int((end - start) * 1000)}ms")
    
    async def watch(path):
        async for _ in awatch(path):
            recompile()

    try:
        recompile()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(watch(base))
    except KeyboardInterrupt:
        pass
    out_root.cleanup()
