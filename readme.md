## How to use the .env in project root

For using the .env variable in root folder automatically: 
- use python environments extension!
- content of settings.json :
{
  "python.terminal.useEnvFile": true,
  "python.envFile": "${workspaceFolder}\\.env"
}

- content of .env file:

PYTHONPATH=E:\projects\studienarbeit

that should be enough to automatically use the .env so that folder like tests and experiments can import other files


### Boilerplate to manually get the root of the project
import os, sys
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
root = os.getenv("PYTHONPATH")
sys.path.append(root)

##  