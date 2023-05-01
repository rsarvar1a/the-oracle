# Oracle

A command and response management system for The Forest.

# Getting Started 

Install dependencies with Poetry.
```zsh
$ poetry env use 3.11 
$ poetry install
```

Configure `oracle` by providing a configuration file:
```json
{
  "administrators": [],
  "asset_path": "path/to/assets/folder/",
  "command_path": "path/to/commands/folder/",
  "prefix": "?",
  "token": "<YOUR TOKEN HERE>"
}
```

**Do not commit a `config.json` to version control!**

Run `oracle`.
```zsh
$ poetry run oracle -c "path/to/config/file.json"
```
