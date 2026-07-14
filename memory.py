import json
import os

MEMORY_FILE = "memory/data.json"

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}

    with open(MEMORY_FILE, "r") as file:
        return json.load(file)

def save_memory(data):
    with open(MEMORY_FILE, "w") as file:
        json.dump(data, file, indent=4)

def remember(key, value):
    data = load_memory()
    data[key] = value
    save_memory(data)

def recall(key):
    data = load_memory()
    return data.get(key)