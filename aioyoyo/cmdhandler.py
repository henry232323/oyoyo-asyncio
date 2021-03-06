#!/usr/bin/python3
# Copyright (c) 2016-2017, henry232323
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import inspect
import logging
import traceback

from .oyoyo.parse import parse_nick
from .oyoyo.cmdhandler import CommandError, NoSuchCommandError, ProtectedCommandError, IRCClientError

from . import helpers


def protected(func):
    """Decorator to protect functions from being called as commands"""
    func.protected = True
    return func


class CommandHandler(object):
    """ The most basic CommandHandler """

    def __init__(self, client):
        self.client = client

    @protected
    def get(self, in_command_parts):
        """Finds a command
        commands may be dotted. each command part is checked that it does
        not start with and underscore and does not have an attribute
        "protected". if either of these is true, ProtectedCommandError
        is raised.
        its possible to pass both "command.sub.func" and
        ["command", "sub", "func"].
        """
        if isinstance(in_command_parts, (bytes)):
            in_command_parts = in_command_parts.split(".".encode())
        elif isinstance(in_command_parts, (str)):
            in_command_parts = in_command_parts.split('.')
        command_parts = in_command_parts[:]

        p = self
        while command_parts:
            cmd = command_parts.pop(0)
            if type(cmd) is bytes:
                cmd = cmd.decode()
            if cmd.startswith('_'):
                raise ProtectedCommandError(in_command_parts)

            try:
                f = getattr(p, cmd)
            except AttributeError:
                raise NoSuchCommandError(in_command_parts)

            if hasattr(f, 'protected'):
                raise ProtectedCommandError(in_command_parts)

            if isinstance(f, CommandHandler) and command_parts:
                return f.get(command_parts)
            p = f

        return f

    @protected
    async def run(self, command, *args):
        """Finds and runs a command"""
        logging.debug("processCommand %s(%s)" % (command, args))
        logging.info("processCommand %s(%s)" % (command, args))

        try:
            f = self.get(command)
        except NoSuchCommandError:
            self.__unhandled__(command, *args)
            return

        logging.debug('f %s' % f)

        try:
            await f(self.client, *args)
        except Exception as e:
            logging.error('command raised %s' % e)
            logging.error(traceback.format_exc())
            raise CommandError(command)

    @protected
    def __unhandled__(self, cmd, *args):
        """The default handler for commands. Override this method to
        apply custom behavior (example, printing) unhandled commands.
        """
        logging.debug('unhandled command %s(%s)' % (cmd, args))


class DefaultCommandHandler(CommandHandler):
    """ CommandHandler that provides methods for the normal operation of IRC.
    If you want your bot to properly respond to pings, etc, you should subclass this.
    """

    async def ping(self, prefix, server):
        """Called on PING command, sends back PONG"""
        self.client.send('PONG', server)


class DefaultBotCommandHandler(CommandHandler):
    """Default command handler for bots. Methods/Attributes are made
    available as commands """

    @protected
    def getVisibleCommands(self, obj=None):
        """Gets all visible commands, protected"""
        test = (lambda x: isinstance(x, CommandHandler) or inspect.ismethod(x) or inspect.isfunction(x))
        members = inspect.getmembers(obj or self, test)
        return [m for m, _ in members
                if (not m.startswith('_') and
                    not hasattr(getattr(obj, m), 'protected'))]

    async def help(self, sender, dest, arg=None):
        """List all available commands or get help on a specific command"""
        logging.info('help sender=%s dest=%s arg=%s' % (sender, dest, arg))
        if not arg:
            commands = self.getVisibleCommands()
            commands.sort()
            await helpers.msg(self.client, dest,
                        "available commands: %s" % " ".join(commands))
        else:
            try:
                f = self.get(arg)
            except CommandError as e:
                await helpers.msg(self.client, dest, str(e))
                return

            doc = f.__doc__.strip() if f.__doc__ else "No help available"

            if not inspect.ismethod(f):
                subcommands = self.getVisibleCommands(f)
                if subcommands:
                    doc += " [sub commands: %s]" % " ".join(subcommands)

            await helpers.msg(self.client, dest, "%s: %s" % (arg, doc))


class BotCommandHandler(DefaultCommandHandler):
    """Complete command handler for bots"""

    def __init__(self, client, command_handler):
        DefaultCommandHandler.__init__(self, client)
        self.command_handler = command_handler

    async def privmsg(self, prefix, dest, msg):
        """Called when privmsg command is received, just awaits
        BotCommandHandler.tryBotCommand with the same args"""
        await self.tryBotCommand(prefix, dest, msg)

    @protected
    async def tryBotCommand(self, prefix, dest, msg):
        """Tests a command to see if its a command for the bot, returns True
        and calls self.processBotCommand(cmd, sender) if its is.
        """

        logging.debug("tryBotCommand('%s' '%s' '%s')" % (prefix, dest, msg))

        if dest == self.client.nick:
            dest = parse_nick(prefix)[0]
        elif msg.startswith(self.client.nick):
            msg = msg[len(self.client.nick) + 1:]
        else:
            return False

        msg = msg.strip()

        parts = msg.split(' ', 1)
        command = parts[0]
        arg = parts[1:]

        try:
            await self.command_handler.run(command, prefix, dest, *arg)
        except CommandError as e:
            await helpers.msg(self.client, dest, str(e))
        return True
