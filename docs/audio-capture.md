# Capturing meeting audio

The app records two separate streams in **Online meeting** mode:

| Stream | Label | What it hears |
|---|---|---|
| Microphone | **Me** | your voice |
| Computer audio | **Others** | everything the meeting app plays: remote participants, shared videos |

Because the computer-audio stream is taken digitally from the output device, it works the
same with **speakers or headphones**. Keeping the streams separate is also what produces
the Me / Others speaker split.

## Windows 10 / 11

Nothing to install. The app uses WASAPI loopback on the output device.

1. In Settings, leave **Computer-audio device** on *Default output*, or pick the output
   your meeting app uses (for example your USB headset).
2. In Teams or Zoom, make sure the call audio goes to that same output.
3. Start recording and check that the purple level meter moves when others talk.

Tips

- With speakers (no headphones), your microphone also picks up the remote voices, so the
  same words can appear twice. Use headphones, enable echo cancellation in the meeting app,
  or choose **Computer audio only** when you are only listening.
- Bluetooth headsets switch to a low-quality "hands-free" profile while the mic is in use.
  That is fine for transcription.

## macOS 13+

macOS does not let a Python app capture another app's audio directly. Use the free
**BlackHole** virtual audio device:

1. `brew install blackhole-2ch` (or download from existential.audio/blackhole) and restart CoreAudio when asked.
2. Open **Audio MIDI Setup** → **+** → **Create Multi-Output Device**. Tick your
   speakers or headphones **and** BlackHole 2ch, and set your speakers or headphones as
   *Primary* with drift correction on.
3. Set the Multi-Output Device as the system output (or as the speaker in Teams or Zoom audio settings).
4. In this app's Settings, choose **BlackHole 2ch** as **Computer-audio device**.
5. The first time you record, allow microphone access for your terminal or the app.

Microphone-only (in-person) mode works with no extra setup.

Roadmap: a small ScreenCaptureKit helper (macOS 13+) that captures system audio with no
virtual device (requirements.md P5).

## Linux (best effort)

PulseAudio and PipeWire expose "Monitor of …" sources. They show up as computer-audio devices.

## Troubleshooting

- `meeting-notes devices` lists everything the app can see.
- `meeting-notes doctor` checks devices, engines and AI providers.
- Use the **Test engine (no recognition)** to confirm capture before you install speech models.
- No sound on the Others meter: the meeting app is playing to a different output device than the one selected.
