#!/usr/bin/env python
import os
os.chdir(r'D:\xampp\htdocs\lat1')

import uvicorn
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, log_level="info")