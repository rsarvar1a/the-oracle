from . import formatter
from . import utilities

import discord
import inspect
import json
import logging
import os
import pathlib
import re
import time


class Client(discord.Client):
    def __init__(self, *, options, logging_level):
        """
        Creates a new client with the desired Discord intents.
        """

        self.logger = logging.getLogger("oracles.client")
        self.format = formatter.ColourFormatter()
        self.handle = logging.StreamHandler()

        self.logger.addHandler(self.handle)
        self.handle.setFormatter(self.format)

        self.logger.setLevel(logging_level)
        self.handle.setLevel(logging_level)

        if logging_level == logging.DEBUG:
            self.logger.warn("Running in debugging mode!")

        # Configure the client as provided by the library.
        super_opts = {
            k: v
            for k, v in options.items()
            if k
            in [
                p.name
                for p in inspect.signature(
                    super(Client, self).__init__
                ).parameters.values()
            ]
        }
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, **super_opts)

        # Add custom configuration options belonging to the subclass.
        self_opts = {
            k: v
            for k, v in options.items()
            if k
            in [
                p.name
                for p in inspect.signature(self.configure_options).parameters.values()
            ]
        }
        self.configure_options(**self_opts)

        self.camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")
        self.create_command_library()

    async def action__no_permission(self, function_name, msg, args):
        """
        The default response when a non-administrator uses an admin command.
        """
    
        await msg.channel.send(embed = discord.Embed.from_dict({'description': ":x: You do not have the necessary permissions."}))
        return False

    async def action__no_such_action(self, function_name, msg, args):
        """
        The null action.
        """

        self.logger.error("No such action `{k}`!".format(k=function_name))
        return False

    async def action_create_channel_in_category(self, function_name, msg, args):
        """
        Creates a channel in the same category as the message.
        args:
        - name: the desired channel name
        - duplicate: whether or not to proceed if the category already has a channel with the same name
        - sort_category: whether or not to sort the category by channel name upon insertion
        """

        if not msg.channel.category:
            self.logger.warn(
                "You cannot call `{}` in a channel with no parent category!".format(
                    function_name
                )
            )
            return

        name, duplicate, sort_category = utilities.get_default(
            "name", "duplicate", "sort_category"
        )(args)
        parent, channel_list = msg.channel.category, msg.channel.category.channels

        if duplicate and name in map(lambda ch: ch.name, channel_list):
            return

        # We add the channel using the permission scheme of the parent category.
        new_channel = await parent.create_text_channel(
            name, overwrites=parent.overwrites
        )
        self.logger.info("Created channel {} in {}.".format(name, parent.name))

        if not sort_category:
            return

        # Else, we need to sort the channels in the category alphabetically.
        sorted_channels = sorted(
            new_channel.category.channels, key=(lambda ch: ch.name)
        )
        for index, channel in enumerate(sorted_channels):
            if index == 0:
                self.logger.debug(
                    "Moved channel {} to the top of {}.".format(channel.name, parent)
                )
                await channel.move(beginning=True, category=parent)
            else:
                self.logger.debug(
                    "Moved channel {} right below previous channel {}.".format(
                        channel.name, sorted_channels[index - 1].name
                    )
                )
                await channel.move(after=sorted_channels[index - 1], category=parent)

        return True

    async def action_lockdown(self, function_name, msg, args):
        """
        Pauses all command execution. To recover, run a reload.
        """

        if msg.author.id not in self.administrators:
            await self.action__no_permission(function_name, msg, args)
            self.logger.warn("User <@{}> tried to lockdown.".format(msg.author.id))
            return
    
        for k in self.command_lists:
            if k != "reload":
                self.command_lists.remove(k)

        self.logger.warn("Lockdown; reload to unpause.")
        return True

    async def action_shutdown(self, function_name, msg, args):
        """
        Administrator-gated permission to hard shutdown this instance.
        """

        if msg.author.id not in self.administrators:
            await self.action__no_permission(function_name, msg, args)
            self.logger.warn("User <@{}> tried to shutdown.".format(msg.author.id))
            return 

        await self.close()
        return True

    async def action_reload(self, function_name, msg, args):
        """
        Administrator-gated permission to hard reload the command library for rapid testing.
        """

        if msg.author.id not in self.administrators:
            await self.action__no_permission(function_name, msg, args)
            self.logger.warn("User <@{}> tried to reload.".format(msg.author.id))
            return

        self.logger.warn("Reloading the command library while live!")
        self.create_command_library()
        return True

    async def cmd_execute_actions(self, msg, actions):
        """
        Executes a list of builtin command actions, in the order given.
        """

        # Action lists are optional if the command doesn't have to do anything except
        # sending a response.
        if not actions:
            return True

        statuses = []

        for action in actions:
            action_key, args = utilities.get_default("name", "args")(action)
            function_name = await self.cmd_translate_action_key(action_key)
            status = await getattr(self, function_name, "action__no_such_action")(
                action_key, msg, args
            )
            statuses.append(status)

        return all(s for s in statuses)

    async def cmd_find_correct(self, msg, cmd, candidates):
        """
        Given a list of candidates for this command, find the correct one if it exists.
        """

        valid_candidates = [
            candidate
            for candidate in candidates
            if self.cmd_resolve_context(msg, candidate)
        ]

        if len(valid_candidates) == 0:
            return None
        elif len(valid_candidates) == 1:
            return valid_candidates[0]
        else:
            self.logger.error("Ambiguous command {} in context {}.".format(cmd, msg.id))
            await msg.send(
                content=":x: Something went wrong... let a staff member know!"
            )
            return None

    def cmd_resolve_block_location(self, context, resolve):
        """
        Resolves a location.
        """

        scope, cmp, name = utilities.get_default("scope", "cmp", "name")(resolve)

        location_type = {
            "category": "channel.category",
            "channel": "channel",
            "server": "channel.guild",
        }.get(scope.lower(), None)

        if not location_type:
            self.logger.error("Unknown scope {}.".format(scope))
            return False

        actual_scope = utilities.rgetattr(context, location_type).name

        match cmp:
            case "equals" | "exact" | "is":
                return name == actual_scope
            case "expr" | "like" | "regex":
                try:
                    return re.search(name, actual_scope) is not None
                except Exception:
                    self.logger.error("Invalid regex {}.".format(name))
                    return False

        self.logger.error("Unknown comparator {}.".format(cmp))
        return False

    def cmd_resolve_block_role(self, context, resolve):
        """
        Resolves a role.
        """

        op, name = utilities.get_default("cmp", "name")(resolve)

        match op:
            case "equals" | "exact" | "is":
                return any(r.name == name for r in context.author.roles)
            case "expr" | "like" | "regex":
                try:
                    return any(
                        re.search(name, r.name) is not None
                        for r in context.author.roles
                    )
                except Exception:
                    self.logger.error("Invalid regex {}.".format(name))
                    return False

        self.logger.error("Unknown comparator {}.".format(op))
        return False

    def cmd_resolve_recursive(self, context, resolve, op=None):
        """
        If the resolve scope is a list, true if any(). If the resolve scope is a dict, true if all().
        """

        if isinstance(resolve, list):
            match op:
                case "and":
                    return all(self.cmd_resolve_recursive(context, r) for r in resolve)
                case "or":
                    return any(self.cmd_resolve_recursive(context, r) for r in resolve)
                case "not":
                    return not any(
                        self.cmd_resolve_recursive(context, r) for r in resolve
                    )
                case _:
                    self.logger.error("Unknown list operator {}.".format(op))
                    return False

        # Is this a leaf or a node?
        _and, _or, _not = utilities.get_default("and", "or", "not")(resolve)
        results = [r for r in [_and, _or, _not] if r]

        if len(results) == 1:
            if _and:
                return self.cmd_resolve_recursive(context, resolve["and"], "and")
            if _or:
                return self.cmd_resolve_recursive(context, resolve["or"], "or")
            if _not:
                return self.cmd_resolve_recursive(context, resolve["not"], "not")
        elif len(results) > 1:
            self.logger.error("Ambiguous resolver block: too many operators!")
            return False

        # Otherwise, there is no operator in this dict and thus it's a leaf.
        handler = utilities.get_default("type")(resolve)
        match handler:
            case "location":
                return self.cmd_resolve_block_location(context, resolve)
            case "role":
                return self.cmd_resolve_block_role(context, resolve)
            case _:
                self.logger.error("Unknown resolver leaf type {}.".format(handler))
                return False

    def cmd_resolve_context(self, context, candidate):
        """
        Resolves a context against a candidate.
        """

        resolve = utilities.get_default("resolve")(candidate)

        # The absence of a policy is the same as full policy.
        if not resolve:
            return True

        if not isinstance(resolve, dict):
            self.logger.error("Top level resolver must be a dictionary.")
            return False

        if "and" not in resolve and "or" not in resolve and "not" in resolve:
            self.logger.error("Top level resolver must be 'and', 'or' or 'not'.")

        return self.cmd_resolve_recursive(context, resolve)

    async def cmd_send_response(self, msg, response):
        """
        Sends a response to the command invocation.
        """

        r_type, attachments, content = utilities.get_default(
            "type", "attachments", "content"
        )(response)

        files = []

        if attachments:
            for attachment in attachments:
                path, name = utilities.get_default("path", "name")(attachment)
                path = os.path.join(self.asset_path, path)
                try:
                    with open(os.path.realpath(path), "rb") as fp:
                        files.append(discord.File(fp, filename=name))
                except Exception:
                    self.logger.error("Invalid path {}.".format(path))

        if r_type == "simple":
            args = {"content": content}
            args.update({"file": files[0]} if len(files) == 1 else {"files": files})

            await msg.channel.send(**args)
            return

        # Then we know we're dealing with embeds.
        if isinstance(content, dict):
            contents = [content]
        else:
            contents = content

        embeds = []
        for content in contents:
            if "description" in content:
                content["description"] = re.sub(
                    "\\$\\{PREFIX\\}", self.prefix, content['description']
                )
            embed = discord.Embed.from_dict(content)
            if "image" in content:
                embed.set_image(url=content["image"])
            embeds.append(embed)

        # Dynamically call the send function to support our responses.
        args = {}
        args.update({"file": files[0]} if len(files) == 1 else {"files": files})
        args.update({"embed": embeds[0]} if len(embeds) == 1 else {"embeds": embeds})

        await msg.channel.send(**args)

    async def cmd_translate_action_key(self, action_key):
        """
        Takes a JSON action name and returns the name of the method corresponding to that function.
        """
        return "action_" + self.camel_case_pattern.sub("_", action_key).lower()

    def configure_options(
        self,
        *,
        administrators=[],
        asset_path="./assets/",
        command_path="./commands/",
        prefix="?",
        token=None,
    ):
        """
        Configures the bot given a set of options.
        """

        self.administrators = administrators
        self.asset_path = asset_path
        self.command_path = command_path
        self.prefix = prefix
        self.token = token

    def create_command_library(self):
        """
        Using the command path, creates the custom commands from the JSON specifications.
        """

        self.command_lists = {}
        collision = False

        s = time.perf_counter()
        # Recurse over the commands directory and find every JSON specifying a command.
        # Add the command to the library under every alias specified for that configuration.
        for path in pathlib.Path(self.command_path).rglob("cmd-*.json"):
            with open(path, "r") as f:
                cmd_configs = json.load(f)

                if isinstance(cmd_configs, dict):
                    cmd_configs = [cmd_configs]

                for config in cmd_configs:
                    for alias in config["aliases"]:
                        alias = alias.lower()

                        if alias not in self.command_lists:
                            self.command_lists.update({alias: [config]})
                            self.logger.debug(
                                "Built new command: `{}{}`".format(self.prefix, alias)
                            )
                        else:
                            if not any(
                                existing_command.get("resolve", None)
                                == config.get("resolve", None)
                                for existing_command in self.command_lists[alias]
                            ):
                                self.command_lists[alias].append(config)
                                self.logger.debug(
                                    "Name collision at {prefix}{alias}.".format(
                                        **{"prefix": self.prefix, "alias": alias}
                                    )
                                )
                            else:
                                collision = True
                                self.logger.error(
                                    "True name and config collision at {prefix}{alias}!.".format(
                                        **{"prefix": self.prefix, "alias": alias}
                                    )
                                )
        f = time.perf_counter()

        if collision:
            self.logger.fatal(
                "Resolve naming collisions; overlapping commands might result in undefined behaviour."
            )
        else:
            for k, v in self.command_lists.items():
                self.logger.debug(
                    "Loaded command {}. ({} resolver entr{})".format(
                        k, len(v), "y" if len(v) == 1 else "ies"
                    )
                )
            self.logger.info(
                "Loaded {n} commands successfully! (took {t:0.2f}s)".format(
                    n=len(self.command_lists), t=f-s
                )
            )

    async def on_message(self, message):
        """
        Handles messages by looking them up in the command dictionary.
        """

        s = time.perf_counter()

        # Only respond to messages inside servers.
        if not message.channel.guild:
            return

        if not message.content.lower().startswith(self.prefix):
            return

        # Get the command line formed from this command, after removing the prefix.
        cmd_array = message.content.lower().removeprefix(self.prefix).split()
        cmd, args = cmd_array[0], cmd_array[1:]

        self.logger.debug("Received attempt at a command: `{} <{}>`".format(cmd, args))

        if cmd not in self.command_lists:
            return

        self.logger.debug("Command {} is a command; trying to resolve.".format(cmd))

        exec_config = await self.cmd_find_correct(message, cmd, self.command_lists[cmd])
        if not exec_config:
            return

        self.logger.debug("Resolved command {} to {}.".format(cmd, id(exec_config)))

        response, actions = utilities.get_default("response", "actions")(exec_config)

        if await self.cmd_execute_actions(message, actions):
            await self.cmd_send_response(message, response)

        f = time.perf_counter()

        self.logger.info(
            "Succesfully executed `{pref}{cmd} <{args}>` by {name}. (took {t:0.2f}s)".format(
                name=message.author.name + "#" + message.author.discriminator,
                pref=self.prefix,
                cmd=cmd,
                args=args,
                t=f - s,
            )
        )

        # Delete successful commands only.
        # If a command failed due to context checks, do not even acknowledge it.
        # This protects the identity of secret commands.
        await message.delete()

    def run(self):
        """
        Starts the bot. This call is blocking, and all registrations and configurations should occur before running.
        """
        super().run(self.token)
