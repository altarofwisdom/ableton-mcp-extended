# Ableton MCP Extended
**Control Ableton Live using natural language via AI assistants like Claude, Gemini, or Cursor.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Ableton Live 11+](https://img.shields.io/badge/Ableton%20Live-11+-orange.svg)](https://www.ableton.com/)

---
## 🎬 Overview
This tool is designed for producers, developers, and AI enthusiasts who want to streamline their music production workflow, experiment with generative music, and build custom integrations with Ableton Live through the **Model Context Protocol (MCP)**.

[Watch the Video Demonstration](https://www.youtube.com/watch?v=7ZKPIrJuuKk)

### **The Workflow**
```
👤 "Create a minimalist neo-classical composition similar to Ólafur Arnalds."
🤖 "Creating MIDI clips... Adding effects... Done!"
👤 "Generate a poem in Jim Morrison's style and import it as a spoken-word track."
🤖 "Generating via ElevenLabs... Importing into session... Done!"
```

---
## 🚀 Key Features

### 🎵 Session & Transport
*   **Playback Control:** Start, stop, and continue playback. `stop_all_clips`.
*   **Tempo & Timing:** Set tempo, toggle metronome, and use `tap_tempo`.
*   **Arrangement Navigation:** `jump_by` and `scrub_by` (move playhead by beats).
*   **History:** Complete `undo` and `redo` support.
*   **Information:** `get_session_info`, `get_track_info`.
*   **Capture:** Native `capture_midi` and `trigger_session_record` support.

### 🎛️ Track & Scene Management
*   **Tracks:** Create, delete, and duplicate MIDI, Audio, and Return tracks.
*   **Mixing:** Control Solo, Mute, Arm, Volume (Level), Pan, and Monitoring state.
*   **State:** `set_track_frozen` (Freeze/Unfreeze) and `create_take_lane` (Live 11+ Comping).
*   **Appearance:** Set track names and colors.
*   **Scenes:** Create, delete, duplicate, and fire scenes. Capture currently playing clips into new scenes.

### 🎹 MIDI & Clip Manipulation
*   **Note Editing:** Add, remove, transpose, and quantize MIDI notes.
*   **Processing:** Randomize timing, set note probability, and perform batch edits.
*   **Clips:** Create, clear, and name clips. Set loop parameters and follow actions.
*   **Arrangement Integration:** `duplicate_clip_to_arrangement` (copy session clips to timeline).

### 🔌 Device & Browser Integration
*   **Device Control:** Get/set parameters for any device (normalized 0.0-1.0).
*   **Browser Navigation:** Search and load instruments, effects, kits, and samples.
*   **Automation:** Add and clear automation points for parameters.
*   **Cache:** SQLite-powered lightning-fast search for devices and samples.

### 🎤 AI Voice Integration (ElevenLabs)
*   Generate high-quality speech or sound effects and import them directly into your session as audio tracks.

---
## 🧪 Experimental & Advanced Features

### 🖱️ XY Mouse Controller
A demonstration of building custom real-time controllers. Control any two Ableton parameters simultaneously using your mouse movements.
*   **Ultra-Low Latency:** Uses a high-performance UDP protocol for responsive, jitter-free control.
*   **Extensible:** Serves as a template for building your own hardware or software controllers that talk to Ableton via MCP.

### ⚡ Hybrid TCP/UDP Server
Includes a high-performance UDP side-channel for tasks that require real-time responsiveness (like performance controllers) while maintaining a reliable TCP connection for standard commands.

---
## 🛠️ Installation

For a complete, step-by-step guide on setting up the Remote Script and connecting your AI assistant (Claude, Gemini, or Cursor), please see:

👉 **[INSTALLATION.md](./INSTALLATION.md)**

### **Quick Setup Summary**
1.  Clone the repository and `pip install -e .`
2.  Install the `AbletonMCP` Remote Script in Ableton's user folder.
3.  Enable the script in Ableton Preferences.
4.  Add the MCP server to your AI assistant's configuration.

---
## 🏗️ How It Works

```
      [ You: Natural Language ]
                 │
                 ▼
          [ AI Assistant ]
                 │
                 ▼
           [ MCP Server ] <─── [ ElevenLabs AI ]
                 │                 (Audio)
                 ▼
     [ Ableton Remote Script ]
                 │
                 ▼
        [ Ableton Live API ]
                 │
                 ▼
           [ 🎵 Your Music ]
```

---
## 💬 Support & Community
- **Found a bug?** [Open an issue](https://github.com/uisato/ableton-mcp-extended/issues)
- **Have questions?** [Join discussions](https://github.com/uisato/ableton-mcp-extended/discussions)
- **License:** MIT
