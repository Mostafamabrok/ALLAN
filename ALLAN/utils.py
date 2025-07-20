# utils.py
# This file contains utility functions shared across the ALLAN project.

import time

def log(message: str, source: str = "UnknownSource"):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    
    #There should be a proper logging procedure here, but that can be done later. 
    print(f"[{timestamp}] [{source} LOG]: {message}")