
import discord 
import inspect
import json
import operator
import os
import pathlib
import re
import time
import utilities


class Client (discord.Client):
    
    
    def __init__ (self, options):
        """
        Creates a new client with the desired Discord intents.
        """
        
        # Configure the client as provided by the library.
        super_opts = { 
            k: v for k, v in options.items() 
            if k in [p.name for p in inspect.signature(super().__init__).parameters.values()] 
        }
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(self, intents = intents, **super_opts)
        
        # Add custom configuration options belonging to the subclass.
        self_opts = { 
            k: v for k, v in options.items() 
            if k in [p.name for p in inspect.signature(self.configure_options).parameters.values()] 
        }
        self.configure_options(**self_opts)
        
        self.camel_case_pattern = re.compile(r'(?<!^)(?=[A-Z])')
        self.create_command_library()
    
   
    async def cmd_check_location (self, msg, policy):
        """
        Checks a location configuration to see if it satisfied.
        """
        
        location_type, operator, location = operator.itemgetter('scope', 'cmp', 'name')(policy)
        
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
                return re.match(location, actual_scope) is not None
        
   
    async def cmd_check_locations (self, msg, policy):
        """
        Determines whether the command is being invoked from a valid location or not.
        """
        
        # The absence of a policy is the same as a full policy.
        if not policy:
            return True
        
        allow, deny = operator.itemgetter('allow', 'deny')(policy)
        
        has_allow = True if not allow else any(self.cmd_check_location(msg, location) for location in allow)
        has_deny  = False if not deny else any(self.cmd_check_location(msg, location) for location in deny)
        
        return has_allow and not has_deny
   
   
    async def cmd_check_requirements (self, msg, policy):
        """
        Determines from the command configuration if the command can be used in its current context.
        """
        
        # The absence of a policy is the same as a full policy.
        if not policy:
            return True

        locations, roles, permissions = operator.itemgetter('locations', 'permissions', 'roles')(policy)

        check_locations   = await self.cmd_check_locations(msg, locations)
        check_permissions = await self.cmd_check_permissions(msg, permissions)
        check_roles       = await self.cmd_check_roles(msg, roles)
        
        return check_locations and check_permissions and check_roles
        
    
    async def cmd_check_role (self, msg, policy):
        """
        Determines whether the given role is satisfied.
        """
        
        operator, name = operator.itemgetter('cmp', 'name')(policy)
        
        match operator:
            case "equals" | "exact" | "is":
                return any(r.name == name for r in msg.author.roles)
            case "expr" | "like" | "regex":
                return any(re.match(name, r.name) is not None for r in msg.author.roles)
        
    
    async def cmd_check_roles (self, msg, roles):
        """
        Ensures the member has the necessary roles to perform the given action.
        """
        
        # The absence of a policy is the same as a full policy.
        if not roles:
            return True 
        
        allow, deny = operator.itemgetter('allow', 'deny')(roles)

        has_allow = True if not allow else any(self.cmd_check_role(msg, role) for role in allow)
        has_deny  = False if not deny else any(self.cmd_check_role(msg, role) for role in deny)
        
        return has_allow and not has_deny
                    
    
    async def cmd_execute_actions (self, msg, actions):
        """
        Executes a list of builtin command actions, in the order given.
        """
        
        for action in actions:
            action_key, args = operator.itemgetter("name", "args")(action)
            function_name = await self.cmd_translate_action_key(action_key)
            await self.getattr(function_name, "action_no_such_action")(action_key, msg, args)
    
    
    async def cmd_send_response (self, msg, response):
        """
        Sends a response to the command invocation.
        """
        
        r_type, attachments, content = operator.itemgetter('type', 'attachments', 'content')(response)
        
        files = []
        for attachment in attachments:
            path, name = operator.itemgetter("path", "name")(attachment)
            with open(os.path.realpath(os.path.join(self.asset_path, path)), "rb") as fp:
                files.append(discord.File(fp, filename = name))
        if len(files) == 0:
            files = None
        
        if   r_type == 'simple':
            await msg.channel.send(files = files, content = content)
        elif r_type == 'embed':
            await msg.channel.send(files = files, embed = content)


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
            with json.load(open(path, "r")) as cmd_config:
                for alias in cmd_config['aliases']:
                    try:
                        self.commands.update({alias: cmd_config})
                    except KeyError:
                        print("Name collision at {prefix}{alias}!.".format(**{ "prefix": self.prefix, "alias": alias }))
                        collision = True
        f = time.perf_counter()

        if collision:
            print("FATAL ERROR: Resolve the above command name collisions.")
            exit(1)
        else:
            print("Loaded commands successfully! (took {0.2f}s)".format(f - s))
        
    
    async def on_message (self, message):
        """
        Handles messages by looking them up in the command dictionary. 
        """
        
        # Only respond to messages inside servers.
        if not message.channel.guild:
            return
                
        if not message.content.lower().startswith(self.prefix):
            return
        
        # Get the command line formed from this command, after removing the prefix.
        cmd_array = message.content.lower().removeprefix(self.prefix).split()
        cmd, args = cmd_array[0], cmd_array[1:]
        
        if cmd not in self.commands:
            return
        
        requirements, response, actions = operator.itemgetter("requirements", "response", "actions")(self.commands[cmd])
        
        if not await self.cmd_check_requirements(message, requirements):
            return 
        
        await self.cmd_send_response(message, response)
        await self.cmd_execute_actions(message, actions)
        
        # Delete successful commands only. 
        # If a command failed due to context checks, do not even acknowledge it.
        # This protects the identity of secret commands.
        await message.delete()


    def run (self):
        """
        Starts the bot. This call is blocking, and all registrations and configurations should occur before running.
        """
        super().run(self, self.token)