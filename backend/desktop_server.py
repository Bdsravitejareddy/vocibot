import multiprocessing
import os

import uvicorn

if __name__ == "__main__":
    # Model libraries start multiprocessing helpers (e.g. a resource tracker).
    # In the frozen app a helper re-executes this entry point, which must run
    # the helper instead of starting a second server on the same port.
    multiprocessing.freeze_support()
    uvicorn.run("app.main:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")), workers=1)
