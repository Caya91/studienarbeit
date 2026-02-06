## Setup

create ".env" file in the project root "studienarbeit" with the following content
'''
PYTHONPATH=<path-to-studienarbeit>
'''

## How to use the .env in project root

For using the .env variable in root folder automatically: 
- use python environments extension in vs code
- content of settings.json :
{
  "python.terminal.useEnvFile": true,
  "python.envFile": "${workspaceFolder}\\.env"
}

that should be enough to automatically use the .env so that folder like tests and experiments can import other files
