# Commands

Commands are specified by creating `json` files in your commands path. The name of each `json` file 
should be `cmd-<command-name>.json`, where `<command-name>` is the descriptive name for your command.
You can also put multiple definitions into a list and store them as a group in one command file.

The structure of a command is:
```json
{
    "aliases": [],
    "resolve": {},
    "response": {},
    "actions": []
}
```

---
## aliases

You must specify at least one alias.

---
## resolve

The resolver of a command specifies when and how it can be invoked. The resolve block is a recursive tree 
of requirements. Leaf nodes are location-checks or role-checks, and live inside lists anchored to list 
operators.

The following list operators are allowed:
- `and`: matches if each child node in the list is true
- `not`: matches if no child node in the list is true
- ` or`: matches if at least one child node in the list is true

The following leaf-node comparators are allowed:
- `exact`: matches exactly on the location, permission or role name
- ` expr`: matches the location, permission, or role name on a regular expression

### locations

You can choose to restrict the activation of a command to a subset of locations, by name.

The following scopes are available:
- `category`: refers to a category channel
- ` channel`: refers to a text channel
- `  server`: refers to a server

Each location block has the following structure:
```json
{
    "type": "location",
    "scope": "location scope",
    "cmp": "operator",
    "name": "location name"
}
```

### roles

You can limit the use of a command to users based on the presence or absence of roles.

Each role block has the following structure:
```json
{
    "type": "role",
    "cmp": "operator",
    "name": "role name"
}
```

---
## response

The response of a command dictates how the bot responds to the command. 

The response has the following attributes:
- `       type`: specifies whether the content is `message` or `embed`
- `attachments`: contains a list of attachments, up to 10
- `    content`: an `embed` object, if the type is `embed`, otherwise a message string

If the type is `embed`, you can also include a list of embeds (also up to 10).

### attachments

An attachment has the following attributes:
- `path`: specifies a path to a file
- `name`: renames the attachment, which can then be referenced in an embedded message

---
## actions

The bot is capable of taking several built-in actions. The actions provided in the 
`actions` list are run sequentially in the order given.

The structure of an action is:
```json
{
    "name": "action-name",
    "args": {}
}
```

### `createChannelInCategory`

Creates a channel in the same category as the command invocation. The original category
cannot be `None`.
```
{
    "name": "the channel name",
    "duplicate": "whether or not to proceed if a channel in the category already has this name"
    "sort_category": "whether to sort the channels in the category by name upon insertion"
}
```
