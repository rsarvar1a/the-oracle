
from . import formatter
from . import utilities

import discord 
import inspect
import json
import logging
import operator
import os
import pathlib
import re
import sys
import time


class Client (discord.Client):
    
    
    def __init__ (self, *, options, logging_level):
        """
        Creates a new client with the desired Discord intents.
        """
             
        self.logger = logging.getLogger('oracles.client')        
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
            k: v for k, v in options.items() 
            if k in [p.name for p in inspect.signature(super(Client, self).__init__).parameters.values()] 
        }
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents = intents, **super_opts)
                   
        # Add custom configuration options belonging to the subclass.
        self_opts = { 
            k: v for k, v in options.items() 
            if k in [p.name for p in inspect.signature(self.configure_options).parameters.values()] 
        }     
        self.configure_options(**self_opts)
        
        self.camel_case_pattern = re.compile(r'(?<!^)(?=[A-Z])')
        self.create_command_library()
    
   
    async def action__no_such_action (self, function_name, msg, args):
        """
        The null action.
        """
        
        self.logger.error("No such action `{k}`!".format(k = function_name))
        return
    
    
    async def action_create_channel_in_category (self, function_name, msg, args):
        """
        Creates a channel in the same category as the message.
        args:
        - name: the desired channel name
        - duplicate: whether or not to proceed if the category already has a channel with the same name
        - sort_category: whether or not to sort the category by channel name upon insertion
        """
        
        if not msg.channel.category:
            self.logger.warn("You cannot call `{}` in a channel with no parent category!".format(function_name))
            return
        
        name, duplicate, sort_category = utilities.get_default('name', 'duplicate', 'sort_category')(args)
        parent, channel_list = msg.channel.category, msg.channel.category.channels
        
        if duplicate and name in map(lambda ch: ch.name, channel_list):
            return 
        
        # We add the channel using the permission scheme of the parent category.
        new_channel = await parent.create_text_channel(name, overwrites = parent.overwrites)
        self.logger.info("Created channel {} in {}.".format(name, parent.name))
        
        if not sort_category:
            return 
        
        # Else, we need to sort the channels in the category alphabetically.
        sorted_channels = sorted(new_channel.category.channels, key = (lambda ch: ch.name))
        for index, channel in enumerate(sorted_channels):
            if index == 0:
                self.logger.debug("Moved channel {} to the top of {}.".format(channel.name, parent))
                await channel.move(beginning = True, category = parent)
            else:
                self.logger.debug("Moved channel {} right below previous channel {}.".format(channel.name, sorted_channels[index - 1].name))
                await channel.move(after = sorted_channels[index - 1], category = parent)
            
        return
        
        
    async def action_reload (self, function_name, msg, args):
        """
        Administrator-gated permission to hard reload the command library for rapid testing.
        """
        
        self.logger.warn("Reloading the command library while live!")
        self.create_command_library()
    
   
    def cmd_check_location (self, msg, policy):
        """
        Checks a location configuration to see if it satisfied.
        """
        
        location_type, operator, location = utilities.get_default('scope', 'cmp', 'name')(policy)
        
        location_type = {
            "category": "channel.category",
             "channel": "channel",
              "server": "channel.guild"
        }[location_type.lower()]
        actual_scope = utilities.rgetattr(msg, location_type).name
        
        match operator:
            case "equals" | "exact" | "is":
                return location == actual_scope
            case "expr" | "like" | "regex":
                try:
                    return re.match(location, actual_scope) is not None
                except Exception:
                    self.logger.error("Invalid regex {}.".format(location))
                    return False
                
   
    def cmd_check_locations (self, msg, policy):
        """
        Determines whether the command is being invoked from a valid location or not.
        """
        
        # The absence of a policy is the same as a full policy.
        if not policy:
            return True
        
        allow, deny = utilities.get_default('allow', 'deny')(policy)
        
        has_allow = True if not allow else any(self.cmd_check_location(msg, location) for location in allow)
        has_deny  = False if not deny else any(self.cmd_check_location(msg, location) for location in deny)
        
        return has_allow and not has_deny
   
   
    def cmd_check_requirements (self, msg, policy):
        """
        Determines from the command configuration if the command can be used in its current context.
        """
        
        # The absence of a policy is the same as a full policy.
        if not policy:
            return True

        locations, roles = utilities.get_default('locations', 'roles')(policy)

        check_locations   = self.cmd_check_locations(msg, locations)
        check_roles       = self.cmd_check_roles(msg, roles)
        
        return check_locations and check_roles
        
    
    def cmd_check_role (self, msg, policy):
        """
        Determines whether the given role is satisfied.
        """
        
        operator, name = utilities.get_default('cmp', 'name')(policy)
        
        match operator:
            case "equals" | "exact" | "is":
                return any(r.name == name for r in msg.author.roles)
            case "expr" | "like" | "regex":
                try:
                    return any(re.match(name, r.name) is not None for r in msg.author.roles)
                except Exception:
                    self.logger.error("Invalid regex {}.".format(name))
                    return False
                
    
    def cmd_check_roles (self, msg, roles):
        """
        Ensures the member has the necessary roles to perform the given action.
        """
        
        # The absence of a policy is the same as a full policy.
        if not roles:
            return True 
        
        allow, deny = utilities.get_default('allow', 'deny')(roles)

        has_allow = True if not allow else any(self.cmd_check_role(msg, role) for role in allow)
        has_deny  = False if not deny else any(self.cmd_check_role(msg, role) for role in deny)
        
        return has_allow and not has_deny
                    
    
    async def cmd_execute_actions (self, msg, actions):
        """
        Executes a list of builtin command actions, in the order given.
        """
        
        # Action lists are optional if the command doesn't have to do anything except 
        # sending a response.
        if not actions:
            return
        
        for action in actions:
            action_key, args = utilities.get_default("name", "args")(action)
            function_name = await self.cmd_translate_action_key(action_key)
            await getattr(self, function_name, "action__no_such_action")(action_key, msg, args)
    
    
    async def cmd_send_response (self, msg, response):
        """
        Sends a response to the command invocation.
        """
        
        r_type, attachments, content = utilities.get_default('type', 'attachments', 'content')(response)
        
        files = []
        
        if attachments:
            for attachment in attachments:
                path, name = utilities.get_default("path", "name")(attachment)
                path = os.path.join(self.asset_path, path)
                try:
                    with open(os.path.realpath(path), "rb") as fp:
                        files.append(discord.File(fp, filename = name))
                except Exception:
                    self.logger.error("Invalid path {}.".format(path))

        if r_type == 'simple':
            args = {'content': content}
            args.update({'file': files[0]} if len(files) == 1 else {'files': files})
            
            await msg.channel.send(**args)
            return

        # Then we know we're dealing with embeds.
        if isinstance(content, dict):
            contents = [content]
        else:
            contents = content
        
        embeds = []
        for content in contents:
            embed = discord.Embed.from_dict(content)
            if 'image' in content:
                embed.set_image(url = content['image'])
            embeds.append(embed)
        
        # Dynamically call the send function to support our responses.
        args = {}
        args.update({'file': files[0]} if len(files) == 1 else {'files': files})
        args.update({'embed': embeds[0]} if len(embeds) == 1 else {'embeds': embeds})
        
        await msg.channel.send(**args)


    async def cmd_translate_action_key (self, action_key):
        """
        Takes a JSON action name and returns the name of the method corresponding to that function.
        """
        return "action_" + self.camel_case_pattern.sub('_', action_key).lower()
    

    def configure_options (self, *, asset_path = "./assets/", command_path = "./commands/", prefix = "?", token = None):
        """
        Configures the bot given a set of options.
        """
        
        self.asset_path   = asset_path
        self.command_path = command_path
        self.prefix       = prefix
        self.token        = token
    
    
    def create_command_library (self):
        """
        Using the command path, creates the custom commands from the JSON specifications.
        """
        
        self.commands = {}
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
                    for alias in config['aliases']:
                        alias = alias.lower()
                        if alias not in self.commands:
                            self.commands.update({alias: config})
                            self.logger.debug("Built command: `{}{}`".format(self.prefix, alias))
                        else:
                            self.logger.error("Name collision at {prefix}{alias}!.".format(**{ "prefix": self.prefix, "alias": alias }))
                            collision = True
        f = time.perf_counter()

        if collision:
            self.logger.fatal("Resolve the above command name collisions.")
            exit(1)
        else:
            self.logger.info("Loaded commands successfully! (took {0:2f}s)".format(f - s))
        
    
    async def on_message (self, message):
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
        
        if cmd not in self.commands:
            return
        
        requirements, response, actions = utilities.get_default("requirements", "response", "actions")(self.commands[cmd])
        
        if not self.cmd_check_requirements(message, requirements):
            self.logger.warn("Failed requirements check on `{pref}{cmd} <{args}>` by {name} (message id {id}).".format(
                name = message.author.name + "#" + message.author.discriminator,
                pref = self.prefix, cmd = cmd, args = args, id = message.id
            ))
            return 
        
        await self.cmd_send_response(message, response)
        await self.cmd_execute_actions(message, actions)
        
        f = time.perf_counter()
        
        self.logger.info("Succesfully executed `{pref}{cmd} <{args}>` by {name}. (took {t:0.2f}s)".format(
            name = message.author.name + "#" + message.author.discriminator,
            pref = self.prefix, cmd = cmd, args = args, t = f - s
        ))
        
        # Delete successful commands only. 
        # If a command failed due to context checks, do not even acknowledge it.
        # This protects the identity of secret commands.
        await message.delete()


    def run (self):
        """
        Starts the bot. This call is blocking, and all registrations and configurations should occur before running.
        """
        super().run(self.token)