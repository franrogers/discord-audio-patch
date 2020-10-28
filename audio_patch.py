#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys

import discord
import numpy as np
import sounddevice as sd


class SoundDeviceSource(discord.AudioSource):
    def __init__(self, device):
        self.stream = sd.InputStream(samplerate=48000,
                                     channels=1,
                                     device=device,
                                     dtype='int16',
                                     latency='low')
        self.stream.start()

    def is_opus(self):
        return False

    def read(self):
        (data, _) = self.stream.read(960)
        data = np.repeat(data, 2, 1)
        return data.data.tobytes()

    def cleanup(self):
        self.stream.stop()


class VoxSource(discord.AudioSource):
    def __init__(self, source):
        self.source = source

        self.active = False
        self.threshold = 16
        self.duration = 25
        self.silent_for = 0

        if self.source.is_opus():
            raise ValueError("cannot use VoxSource with an Opus source")

        self.voice = None
        self.task = None

    def is_opus(self):
        return self.source.is_opus()

    def read(self):
        data = self.source.read()

        if self.active:
            if max(data) < self.threshold:
                self.silent_for += 1
                if self.silent_for >= self.duration:
                    print('VOX off')
                    self.active = False
                    return bytes([])
            else:
                self.silent_for = 0

        return data

    def cleanup(self):
        pass

    async def on_vox(self):
        loop = asyncio.get_running_loop()
        while True:
            start_time = loop.time()
            if not self.active:
                data = self.read()
                if max(data) >= self.threshold:
                    print('VOX on')
                    self.active = True
                    self.voice.play(self)

            await asyncio.sleep(loop.time() - start_time + 0.002)

    def start_vox(self, voice):
        self.voice = voice
        self.task = asyncio.create_task(self.on_vox())

    def stop_vox(self):
        self.task.cancel()


class AudioPatchClient(discord.Client):
    def __init__(self, channel, guild=None, input_device=sd.default.device[0]):
        super().__init__()

        try:
            input_device = int(input_device)
        except ValueError:
            pass
        real_source = SoundDeviceSource(device=input_device)
        self.source = VoxSource(real_source)

        try:
            self.channel_id = int(channel)
        except ValueError:
            self.channel_id = None
            self.channel_name = channel
        self.guild = guild

        self.voice = None

    async def on_ready(self):
        print("Logged on as", self.user)

        if self.channel_id is not None:
            channel = self.get_channel(self.channel_id)
        else:
            channel = None
            for guild in self.guilds:
                if self.guild and guild.name != self.guild:
                    continue
                for guild_channel in guild.voice_channels:
                    if guild_channel.name == self.channel_name:
                        channel = guild_channel
                        break
            if not channel:
                print("{0}: error: can't find channel '{1}'"
                      .format(sys.argv[0], self.channel_id),
                      file=sys.stderr)
                sys.exit(1)

        self.voice = await channel.connect()
        print("Connected to voice channel", self.voice.channel.name)

        self.source.start_vox(self.voice)


def main():
    parser = argparse.ArgumentParser(
        description="Patch a pair of audio devices to a Discord voice channel")
    parser.add_argument('channel', metavar='CHANNEL', nargs='?',
                        help=
                        "voice channel to patch (channel ID or name)")
    parser.add_argument('--guild',
                        default=None,
                        help="guild name")
    parser.add_argument('--token',
                        default=os.environ.get('DISCORD_TOKEN', None),
                        help="Discord token (default: $DISCORD_TOKEN)")
    parser.add_argument('--input',
                        default=sd.default.device[0],
                        help="input audio device (ID or name)")
    parser.add_argument('--list-devices', action='store_true',
                        help="list audio devices")
    args = parser.parse_args()

    if args.list_devices:
        print('Input devices:')
        device_id = 0
        for device in sd.query_devices():
            if device['max_input_channels'] > 0:
                print('  {0}:'.format(device_id), device['name'])
            device_id += 1
        print()
        sys.exit(0)

    if not args.token:
        print("{0}: error: --token or $DISCORD_TOKEN required".format(sys.argv[0]),
              file=sys.stderr)
        sys.exit(1)

    if args.channel is None:
        print("{0}: error: CHANNEL required".format(sys.argv[0]),
              file=sys.stderr)
        sys.exit(1)

    client = AudioPatchClient(channel=args.channel,
                              guild=args.guild,
                              input_device=args.input)
    client.run(args.token)


if __name__ == '__main__':
    main()
