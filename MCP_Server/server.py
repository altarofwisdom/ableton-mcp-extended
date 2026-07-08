# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "create_clip", "add_notes_to_clip", "set_clip_name",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "set_clip_automation_step", "clear_clip_automation",
            "start_playback", "stop_playback", "load_instrument_or_effect",
            "load_browser_item", "load_sample_by_name", "load_sample_by_path",
            "delete_track", "duplicate_track", "create_return_track", "delete_return_track",
            "create_scene", "delete_scene", "duplicate_scene", "capture_and_insert_scene",
            "stop_all_clips", "trigger_session_record", "set_track_monitoring", "tap_tempo",
            "jump_by", "scrub_by", "duplicate_clip_to_arrangement", "set_track_frozen", "create_take_lane",
            "jump_to_next_cue", "jump_to_prev_cue", "set_or_delete_cue", "set_song_scale",
            "set_track_output_routing", "select_track", "set_track_fold_state"
        ]
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            # Set timeout based on command type
            timeout = 30.0 if is_modifying_command else 15.0
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    name="AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection
    
    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"

@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": index})
        return f"Created new audio track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"

@mcp.tool()
def delete_track(ctx: Context, track_index: int) -> str:
    """
    Delete a track from the Ableton session.

    Parameters:
    - track_index: The index of the track to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_track", {"track_index": track_index})
        return f"Deleted track at index {track_index}"
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        return f"Error deleting track: {str(e)}"

@mcp.tool()
def duplicate_track(ctx: Context, track_index: int) -> str:
    """
    Duplicate an existing track.

    Parameters:
    - track_index: The index of the track to duplicate
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_track", {"track_index": track_index})
        return f"Duplicated track at index {track_index}"
    except Exception as e:
        logger.error(f"Error duplicating track: {str(e)}")
        return f"Error duplicating track: {str(e)}"

@mcp.tool()
def create_return_track(ctx: Context) -> str:
    """Create a new return track in the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_return_track")
        return "Created new return track"
    except Exception as e:
        logger.error(f"Error creating return track: {str(e)}")
        return f"Error creating return track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.
    
    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def set_track_color(ctx: Context, track_index: int, color: int) -> str:
    """
    Set the color of a track using an RGB integer value.
    
    Parameters:
    - track_index: The index of the track to change
    - color: RGB integer value (e.g., 0xFF0000 for red)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_color", {"track_index": track_index, "color": color})
        return f"Set track {track_index} color to {hex(result.get('color'))}"
    except Exception as e:
        logger.error(f"Error setting track color: {str(e)}")
        return f"Error setting track color: {str(e)}"

@mcp.tool()
def set_track_color_index(ctx: Context, track_index: int, color_index: int) -> str:
    """
    Set the color of a track using Ableton's color palette index (0-69).
    
    Parameters:
    - track_index: The index of the track to change
    - color_index: Palette index (0-69)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_color_index", {"track_index": track_index, "color_index": color_index})
        return f"Set track {track_index} color index to {result.get('color_index')}"
    except Exception as e:
        logger.error(f"Error setting track color index: {str(e)}")
        return f"Error setting track color index: {str(e)}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.
    
    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def get_notes_from_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Get all MIDI notes from a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_notes_from_clip", {"track_index": track_index, "clip_index": clip_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting notes from clip: {str(e)}")
        return f"Error getting notes: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.
    
    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    
    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

@mcp.tool()
def undo(ctx: Context) -> str:
    """Undo the last action in Ableton."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("undo")
        if result.get("success"):
            return "Undone successfully"
        else:
            return result.get("message", "Nothing to undo")
    except Exception as e:
        logger.error(f"Error undoing: {str(e)}")
        return f"Error undoing: {str(e)}"

@mcp.tool()
def redo(ctx: Context) -> str:
    """Redo the last undone action in Ableton."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("redo")
        if result.get("success"):
            return "Redone successfully"
        else:
            return result.get("message", "Nothing to redo")
    except Exception as e:
        logger.error(f"Error redoing: {str(e)}")
        return f"Error redoing: {str(e)}"

@mcp.tool()
def set_track_solo(ctx: Context, track_index: int, solo: bool) -> str:
    """
    Set the solo state of a track.
    
    Parameters:
    - track_index: The index of the track
    - solo: True to solo, False to unsolo
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_solo", {"track_index": track_index, "solo": solo})
        state = "soloed" if result.get("solo") else "unsoloed"
        return f"Track {track_index} {state}"
    except Exception as e:
        logger.error(f"Error setting track solo: {str(e)}")
        return f"Error setting track solo: {str(e)}"

@mcp.tool()
def set_track_mute(ctx: Context, track_index: int, mute: bool) -> str:
    """
    Set the mute state of a track.
    
    Parameters:
    - track_index: The index of the track
    - mute: True to mute, False to unmute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_mute", {"track_index": track_index, "mute": mute})
        state = "muted" if result.get("mute") else "unmuted"
        return f"Track {track_index} {state}"
    except Exception as e:
        logger.error(f"Error setting track mute: {str(e)}")
        return f"Error setting track mute: {str(e)}"

@mcp.tool()
def set_track_arm(ctx: Context, track_index: int, arm: bool) -> str:
    """
    Set the arm state of a track.
    
    Parameters:
    - track_index: The index of the track
    - arm: True to arm, False to unarm
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_arm", {"track_index": track_index, "arm": arm})
        if result.get("success") == False:
            return result.get("message", "Could not arm track")
        state = "armed" if result.get("arm") else "unarmed"
        return f"Track {track_index} {state}"
    except Exception as e:
        logger.error(f"Error setting track arm: {str(e)}")
        return f"Error setting track arm: {str(e)}"

@mcp.tool()
def create_scene(ctx: Context, index: int = -1) -> str:
    """
    Create a new scene in Ableton.
    
    Parameters:
    - index: The index to insert the scene at (-1 = end)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {"index": index})
        return f"Created scene at index {result.get('scene_index')}"
    except Exception as e:
        logger.error(f"Error creating scene: {str(e)}")
        return f"Error creating scene: {str(e)}"

@mcp.tool()
def fire_scene(ctx: Context, scene_index: int) -> str:
    """
    Fire a scene in Ableton.
    
    Parameters:
    - scene_index: The index of the scene to fire
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_scene", {"scene_index": scene_index})
        return f"Fired scene {scene_index}"
    except Exception as e:
        logger.error(f"Error firing scene: {str(e)}")
        return f"Error firing scene: {str(e)}"

@mcp.tool()
def delete_scene(ctx: Context, scene_index: int) -> str:
    """
    Delete a scene in Ableton.
    
    Parameters:
    - scene_index: The index of the scene to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_scene", {"scene_index": scene_index})
        return f"Deleted scene {scene_index}"
    except Exception as e:
        logger.error(f"Error deleting scene: {str(e)}")
        return f"Error deleting scene: {str(e)}"

@mcp.tool()
def duplicate_scene(ctx: Context, scene_index: int) -> str:
    """
    Duplicate a scene in Ableton.

    Parameters:
    - scene_index: The index of the scene to duplicate
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_scene", {"scene_index": scene_index})
        return f"Duplicated scene {scene_index}"
    except Exception as e:
        logger.error(f"Error duplicating scene: {str(e)}")
        return f"Error duplicating scene: {str(e)}"

@mcp.tool()
def capture_and_insert_scene(ctx: Context) -> str:
    """
    Captures all currently playing clips into a new scene.
    This is Ableton's 'Capture and Insert Scene' feature.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("capture_and_insert_scene")
        return "Captured currently playing clips into a new scene"
    except Exception as e:
        logger.error(f"Error capturing scene: {str(e)}")
        return f"Error capturing scene: {str(e)}"

@mcp.tool()
def set_metronome(ctx: Context, enabled: bool) -> str:
    """
    Enable or disable the metronome in Ableton.
    
    Parameters:
    - enabled: True to enable, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_metronome", {"enabled": enabled})
        state = "enabled" if result.get("enabled") else "disabled"
        return f"Metronome {state}"
    except Exception as e:
        logger.error(f"Error setting metronome: {str(e)}")
        return f"Error setting metronome: {str(e)}"

@mcp.tool()
def capture_midi(ctx: Context) -> str:
    """
    Capture recently played MIDI notes even if not recording.
    This is Ableton's 'Capture MIDI' feature.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("capture_midi")
        if result.get("success"):
            return "MIDI captured successfully"
        else:
            return result.get("message", "Nothing to capture")
    except Exception as e:
        logger.error(f"Error capturing MIDI: {str(e)}")
        return f"Error capturing MIDI: {str(e)}"

@mcp.tool()
def stop_all_clips(ctx: Context) -> str:
    """Immediately stops all playing clips across all tracks."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_all_clips")
        return "Stopped all clips"
    except Exception as e:
        logger.error(f"Error stopping all clips: {str(e)}")
        return f"Error stopping all clips: {str(e)}"

@mcp.tool()
def trigger_session_record(ctx: Context) -> str:
    """Toggle or start session view recording."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("trigger_session_record")
        return "Triggered session record"
    except Exception as e:
        logger.error(f"Error triggering session record: {str(e)}")
        return f"Error triggering session record: {str(e)}"

@mcp.tool()
def set_track_monitoring(ctx: Context, track_index: int, state: int) -> str:
    """
    Set the monitoring state for a track.
    
    Parameters:
    - track_index: The index of the track
    - state: Monitoring state (0: In, 1: Auto, 2: Off)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_monitoring", {
            "track_index": track_index,
            "state": state
        })
        if "error" in result:
            return f"Error: {result['error']}"
        
        monitoring_names = ["In", "Auto", "Off"]
        state_name = monitoring_names[result.get("state", state)]
        return f"Set track {track_index} monitoring to {state_name}"
    except Exception as e:
        logger.error(f"Error setting track monitoring: {str(e)}")
        return f"Error setting track monitoring: {str(e)}"

@mcp.tool()
def tap_tempo(ctx: Context) -> str:
    """Programmatic tap-tempo trigger."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("tap_tempo")
        return "Tapped tempo"
    except Exception as e:
        logger.error(f"Error tapping tempo: {str(e)}")
        return f"Error tapping tempo: {str(e)}"

@mcp.tool()
def jump_by(ctx: Context, beats: float) -> str:
    """
    Jump the playhead forward or backward by a number of beats.
    
    Parameters:
    - beats: Number of beats to jump (positive for forward, negative for backward)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("jump_by", {"beats": beats})
        direction = "forward" if beats > 0 else "backward"
        return f"Jumped {abs(beats)} beats {direction}"
    except Exception as e:
        logger.error(f"Error jumping playhead: {str(e)}")
        return f"Error jumping playhead: {str(e)}"

@mcp.tool()
def scrub_by(ctx: Context, beats: float) -> str:
    """
    Scrub the playhead by a number of beats.
    
    Parameters:
    - beats: Number of beats to scrub
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("scrub_by", {"beats": beats})
        return f"Scrubbed by {beats} beats"
    except Exception as e:
        logger.error(f"Error scrubbing playhead: {str(e)}")
        return f"Error scrubbing playhead: {str(e)}"

@mcp.tool()
def duplicate_clip_to_arrangement(ctx: Context, track_index: int, clip_index: int, target_time: float) -> str:
    """
    Move a session clip into the arrangement timeline.
    
    Parameters:
    - track_index: Index of the track containing the clip
    - clip_index: Index of the clip slot
    - target_time: Position in the arrangement (in beats) to place the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip_to_arrangement", {
            "track_index": track_index,
            "clip_index": clip_index,
            "target_time": target_time
        })
        return f"Duplicated clip from track {track_index}, slot {clip_index} to arrangement at {target_time} beats"
    except Exception as e:
        logger.error(f"Error duplicating clip to arrangement: {str(e)}")
        return f"Error duplicating clip to arrangement: {str(e)}"

@mcp.tool()
def set_track_frozen(ctx: Context, track_index: int, frozen: bool) -> str:
    """
    Freeze or unfreeze a track.
    
    Parameters:
    - track_index: The index of the track
    - frozen: True to freeze, False to unfreeze
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_frozen", {
            "track_index": track_index,
            "frozen": frozen
        })
        if "error" in result:
            return f"Error: {result['error']}"
        
        state = "frozen" if result.get("frozen") else "unfrozen"
        return f"Track {track_index} is now {state}"
    except Exception as e:
        logger.error(f"Error setting track frozen state: {str(e)}")
        return f"Error setting track frozen state: {str(e)}"

@mcp.tool()
def create_take_lane(ctx: Context, track_index: int) -> str:
    """
    Create a new take lane for a track (Live 11+ comping feature).
    
    Parameters:
    - track_index: The index of the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_take_lane", {
            "track_index": track_index
        })
        if "error" in result:
            return f"Error: {result['error']}"
        
        return f"Created new take lane for track {track_index}"
    except Exception as e:
        logger.error(f"Error creating take lane: {str(e)}")
        return f"Error creating take lane: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

@mcp.tool()
def get_audio_input_routings(ctx: Context) -> str:
    """
    Get available audio input devices and channels from the current audio interface.
    Shows all available input routing types and their channels.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_audio_input_routings")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting audio input routings: {str(e)}")
        return f"Error getting audio input routings: {str(e)}"

@mcp.tool()
def get_track_input_routings(ctx: Context, track_index: int) -> str:
    """
    Get input routing information for a specific audio track.

    Parameters:
    - track_index: The index of the audio track to examine
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_input_routings", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track input routings: {str(e)}")
        return f"Error getting track input routings: {str(e)}"

@mcp.tool()
def set_track_input_routing(ctx: Context, track_index: int, routing_type: str = "", routing_channel: str = "") -> str:
    """
    Set the input routing for an audio track.

    Parameters:
    - track_index: The index of the audio track to configure
    - routing_type: The input device/type to route from (e.g., "Ext. In", "Master Track")
    - routing_channel: The specific input channel (e.g., "1/2", "3/4")
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_input_routing", {
            "track_index": track_index,
            "routing_type": routing_type,
            "routing_channel": routing_channel
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting track input routing: {str(e)}")
        return f"Error setting track input routing: {str(e)}"

@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Get detailed information about a device's parameters.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameters", {
            "track_index": track_index,
            "device_index": device_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"

@mcp.tool()
def set_device_parameter(ctx: Context, track_index: int, device_index: int, parameter_index: int, value: float) -> str:
    """
    Set a device parameter value.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_index: The index of the parameter to modify
    - value: The new parameter value (will be clamped to parameter's range)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "value": value
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"

@mcp.tool()
def set_clip_automation_step(
    ctx: Context,
    track_index: int,
    clip_index: int,
    device_index: int,
    parameter_index: int,
    start_time: float,
    duration: float,
    value: float
) -> str:
    """
    Insert a stepped automation segment into a clip envelope for a device parameter.

    Parameters:
    - track_index: Track containing the clip and device
    - clip_index: Clip slot index
    - device_index: Device index on the track
    - parameter_index: Parameter index on the device
    - start_time: Start time in beats within the clip
    - duration: Duration in beats (must be > 0)
    - value: Parameter value to write (will be clamped to parameter range)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_automation_step", {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "start_time": start_time,
            "duration": duration,
            "value": value
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting clip automation step: {str(e)}")
        return f"Error setting clip automation step: {str(e)}"

@mcp.tool()
def clear_clip_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    device_index: int,
    parameter_index: int
) -> str:
    """
    Clear clip automation envelope data for a single device parameter.

    Parameters:
    - track_index: Track containing the clip and device
    - clip_index: Clip slot index
    - device_index: Device index on the track
    - parameter_index: Parameter index on the device
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("clear_clip_automation", {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter_index": parameter_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error clearing clip automation: {str(e)}")
        return f"Error clearing clip automation: {str(e)}"

@mcp.tool()
def clear_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Clear all notes from a MIDI clip without deleting the clip itself.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip to clear
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("clear_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error clearing clip: {str(e)}")
        return f"Error clearing clip: {str(e)}"

@mcp.tool()
def delete_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete a clip from its slot.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting clip: {str(e)}")
        return f"Error deleting clip: {str(e)}"

@mcp.tool()
def remove_notes_from_clip(ctx: Context, track_index: int, clip_index: int, notes_to_remove: list) -> str:
    """
    Remove specific notes from a MIDI clip based on criteria.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip to modify
    - notes_to_remove: List of criteria objects, each can have pitch, start_time, velocity, duration

    Example: [{"pitch": 60}, {"velocity": 127, "start_time": 0.5}]
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("remove_notes_from_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes_to_remove": notes_to_remove
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error removing notes from clip: {str(e)}")
        return f"Error removing notes from clip: {str(e)}"

@mcp.tool()
def delete_device(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Delete a device from a track.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device to delete (0 = first device)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_device", {
            "track_index": track_index,
            "device_index": device_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting device: {str(e)}")
        return f"Error deleting device: {str(e)}"

@mcp.tool()
def get_cached_devices(ctx: Context, device_type: str = "") -> str:
    """
    Get cached devices/plugins for fast access. Cache persists until manually refreshed.

    Parameters:
    - device_type: Specific type to get (vst3_plugins, instruments, audio_effects,
      midi_effects, m4l_instruments, m4l_audio_effects, m4l_midi_effects, drum_racks)
      Leave empty to get all types
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_cached_devices", {
            "device_type": device_type if device_type else None
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting cached devices: {str(e)}")
        return f"Error getting cached devices: {str(e)}"

@mcp.tool()
def refresh_device_cache(ctx: Context) -> str:
    """
    Force refresh of the device/plugin cache. Use this when you install new plugins
    or want to update the available devices list.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("refresh_device_cache")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error refreshing device cache: {str(e)}")
        return f"Error refreshing device cache: {str(e)}"

@mcp.tool()
def get_device_cache_status(ctx: Context) -> str:
    """
    Get information about the device cache status including what's cached and when it was built.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_cache_status")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device cache status: {str(e)}")
        return f"Error getting device cache status: {str(e)}"

@mcp.tool()
def clear_device_cache_file(ctx: Context) -> str:
    """
    Clear the device cache file from disk and reset the in-memory cache.
    This will force a complete rebuild of the device cache on next access.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("clear_device_cache_file")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error clearing device cache file: {str(e)}")
        return f"Error clearing device cache file: {str(e)}"

@mcp.tool()
def search_cached_devices(ctx: Context, search_term: str, category: str = None, max_results: int = 50) -> str:
    """
    Search for devices in the cache by name with intelligent matching.

    Parameters:
    - search_term: The device name or partial name to search for (case-insensitive)
    - category: Optional category to restrict search ("vst3_plugins", "instruments", "audio_effects", etc.)
    - max_results: Maximum number of results to return (default: 50)

    Returns a ranked list of matching devices with their URIs for easy loading.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("search_cached_devices", {
            "search_term": search_term,
            "category": category,
            "max_results": max_results
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error searching cached devices: {str(e)}")
        return f"Error searching cached devices: {str(e)}"


@mcp.tool()
def build_sample_database(ctx: Context, force_rebuild: bool = False) -> str:
    """
    Build or update the SQLite sample database for fast searching.
    This scans all samples in Ableton's browser and creates a searchable database.

    Parameters:
    - force_rebuild: Force rebuild even if database is current (default: False)

    Initial scan may take a few minutes but subsequent searches will be very fast.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("build_sample_database", {"force_rebuild": force_rebuild})

        if "error" in result:
            logger.error(f"Error building sample database: {result['error']}")
            return f"Error building sample database: {result['error']}"

        status = result.get("status", "unknown")
        if status == "database_built":
            samples_count = result.get("samples_count", 0)
            build_time = result.get("build_time", 0)
            return f"Sample database built successfully!\n\nScanned {samples_count:,} items in {build_time:.2f} seconds.\nDatabase saved to: {result.get('database_path', 'unknown')}\n\nYou can now use search_samples for lightning-fast sample searches."
        elif status == "database_current":
            samples_count = result.get("samples_count", 0)
            return f"Sample database is current with {samples_count:,} samples. Use force_rebuild=True to rebuild anyway."
        else:
            return f"Database build status: {status}"

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error building sample database: {error_msg}")
        return f"Error building sample database: {error_msg}"

@mcp.tool()
def get_database_status(ctx: Context) -> str:
    """
    Get the current status of the sample database including scan progress.
    Shows sample count, last scan time, and database file location.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_database_status", {})

        if "error" in result:
            return f"Error getting database status: {result['error']}"

        status = result.get("status", "unknown")
        samples_count = result.get("samples_count", 0)

        if status == "not_initialized":
            return "Sample database not initialized. Use build_sample_database to create it."
        elif status == "empty":
            return "Sample database exists but is empty. Use build_sample_database to populate it."
        elif status == "ready":
            last_scan = result.get("last_scan", "Unknown")
            db_path = result.get("database_path", "Unknown")
            return f"Sample database ready!\n\nSamples indexed: {samples_count:,}\nLast scan: {last_scan}\nDatabase file: {db_path}\n\nUse search_samples for fast searches."
        else:
            return f"Database status: {status} ({samples_count:,} samples)"

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error getting database status: {error_msg}")
        return f"Error getting database status: {error_msg}"

@mcp.tool()
def search_samples(ctx: Context, search_term: str, max_results: int = 200, file_types: list = None, include_paths: bool = False) -> str:
    """
    Fast SQLite-powered search for audio samples. Uses pre-built database for instant results.
    Supports multi-word searches (e.g., "futurephonic kick" finds "01 Adrift Kick - FBD Futurephonic").

    Parameters:
    - search_term: Name or partial name to search for (supports multiple words)
    - max_results: Maximum number of results to return (default: 200)
    - file_types: Optional list of file extensions to filter by (e.g., ["wav", "aiff"])
    - include_paths: Include full file paths in results for direct loading (default: False)

    If database doesn't exist, it will be built automatically on first search.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("search_samples", {
            "search_term": search_term,
            "max_results": max_results,
            "file_types": file_types,
            "include_paths": include_paths
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error searching samples: {str(e)}")
        return f"Error searching samples: {str(e)}"

@mcp.tool()
def load_sample_by_name(ctx: Context, track_index: int, sample_name: str) -> str:
    """
    Load a found sample onto an audio track by its exact name.
    Use this after finding a sample with search_samples.

    Parameters:
    - track_index: Index of the audio track to load the sample onto (0-based)
    - sample_name: Exact name of the sample (e.g., "01 Adrift Kick - FBD Futurephonic.wav")

    The sample will be loaded as an audio clip on the specified track.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_sample_by_name", {
            "track_index": track_index,
            "sample_name": sample_name
        })

        if "error" in result:
            logger.error(f"Error loading sample: {result['error']}")
            return f"Error loading sample: {result['error']}"

        if result.get("loaded", False):
            return f"✅ Sample loaded successfully!\n\nSample: {result.get('sample_name', sample_name)}\nTrack: {result.get('track_name', 'Unknown')} (index {track_index})"
        else:
            return f"Failed to load sample '{sample_name}' onto track {track_index}"

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error loading sample: {error_msg}")
        return f"Error loading sample: {error_msg}"

@mcp.tool()
def load_sample_by_path(ctx: Context, track_index: int, file_path: str) -> str:
    """
    Load a sample onto an audio track directly by its file system path.
    Use this when you have the full file path from search_samples with include_paths=True.

    Parameters:
    - track_index: Index of the audio track to load the sample onto (0-based)
    - file_path: Full file system path to the sample file

    The sample will be loaded as an audio clip on the specified track using direct file access.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_sample_by_path", {
            "track_index": track_index,
            "file_path": file_path
        })

        if "error" in result:
            logger.error(f"Error loading sample by path: {result['error']}")
            return f"Error loading sample by path: {result['error']}"

        if result.get("loaded", False):
            return f"✅ Sample loaded successfully!\n\nFile: {result.get('file_path', file_path)}\nTrack: {result.get('track_name', 'Unknown')} (index {track_index})"
        else:
            return f"Failed to load sample from path '{file_path}' onto track {track_index}"

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error loading sample by path: {error_msg}")
        return f"Error loading sample by path: {error_msg}"

@mcp.tool()
def investigate_sample_database(ctx: Context) -> str:
    """
    Investigate if Ableton has an existing sample database or search system that we can access.
    This checks for database/index/search attributes at the application and browser level,
    as well as any file-based databases in Ableton's preferences.

    Useful for building an efficient sample search system instead of scanning 19,000+ samples each time.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("investigate_sample_database")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error investigating sample database: {str(e)}")
        return f"Error investigating sample database: {str(e)}"

@mcp.tool()
def explore_api(ctx: Context) -> str:
    """
    Explore the Ableton Live Python API to discover available methods and capabilities.
    This is a debugging tool to see what track creation and other methods are available.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("explore_api")

        # Format the results for better readability
        output = ["=== ABLETON LIVE API EXPLORATION ===\n"]

        if "create_methods" in result:
            output.append(f"Found {len(result['create_methods'])} create methods:")
            for method in result["create_methods"]:
                output.append(f"  - {method}")
            output.append("")

        if "track_creation_tests" in result:
            output.append("Track creation method tests:")
            for method, info in result["track_creation_tests"].items():
                status = "EXISTS" if info.get("exists", False) else "NOT FOUND"
                output.append(f"  - {method}: {status}")
                if info.get("type"):
                    output.append(f"    Type: {info['type']}")
            output.append("")

        if "song_methods" in result and result["song_methods"]:
            output.append(f"Found {len(result['song_methods'])} song methods with 'create':")
            for method, info in result["song_methods"].items():
                output.append(f"  - {method}: {info.get('type', 'unknown')}")
            output.append("")

        if "track_methods" in result and result["track_methods"]:
            output.append(f"Sample of track methods ({len(result['track_methods'])} total):")
            for method in list(result["track_methods"].keys())[:15]:
                output.append(f"  - {method}")
            output.append("")

        output.append("Check Ableton Live's log for detailed output.")

        return "\n".join(output)
    except Exception as e:
        logger.error(f"Error exploring API: {str(e)}")
        return f"Error exploring API: {str(e)}"

@mcp.tool()
def delete_return_track(ctx: Context, track_index: int) -> str:
    """
    Delete a return track from the Ableton session.

    Parameters:
    - track_index: The index of the return track to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_return_track", {"track_index": track_index})
        if "error" in result: return f"Error: {result['error']}"
        return f"Deleted return track at index {track_index}"
    except Exception as e:
        logger.error(f"Error deleting return track: {str(e)}")
        return f"Error deleting return track: {str(e)}"

@mcp.tool()
def jump_to_next_cue(ctx: Context) -> str:
    """Jump the playhead to the next cue point in the arrangement."""
    try:
        ableton = get_ableton_connection()
        ableton.send_command("jump_to_next_cue")
        return "Jumped to next cue"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def jump_to_prev_cue(ctx: Context) -> str:
    """Jump the playhead to the previous cue point in the arrangement."""
    try:
        ableton = get_ableton_connection()
        ableton.send_command("jump_to_prev_cue")
        return "Jumped to previous cue"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def set_or_delete_cue(ctx: Context) -> str:
    """Set a new cue point at the current playhead position, or delete if one exists."""
    try:
        ableton = get_ableton_connection()
        ableton.send_command("set_or_delete_cue")
        return "Cue point set/deleted"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def set_song_scale(ctx: Context, root_note: int = None, scale_name: str = None) -> str:
    """
    Set the scale for the current project.
    
    Parameters:
    - root_note: MIDI note number for root (0=C, 1=C#, etc.)
    - scale_name: Name of the scale (e.g., 'Major', 'Minor')
    """
    try:
        ableton = get_ableton_connection()
        params = {}
        if root_note is not None: params["root_note"] = root_note
        if scale_name is not None: params["scale_name"] = scale_name
        result = ableton.send_command("set_song_scale", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def get_track_meter_levels(ctx: Context, track_index: int) -> str:
    """
    Get the current meter levels for a track.
    
    Parameters:
    - track_index: The index of the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_meter_levels", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def set_track_output_routing(ctx: Context, track_index: int, routing_type: str = "", routing_channel: str = "") -> str:
    """
    Set the output routing for a track.

    Parameters:
    - track_index: The index of the track to configure
    - routing_type: The output device/type to route to (e.g., "Ext. Out", "Master Track")
    - routing_channel: The specific output channel (e.g., "1/2", "3/4")
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_output_routing", {
            "track_index": track_index,
            "routing_type": routing_type,
            "routing_channel": routing_channel
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def select_track(ctx: Context, track_index: int) -> str:
    """Select a track in Ableton."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("select_track", {"track_index": track_index})
        return f"Selected track: {result.get('name')}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def set_track_fold_state(ctx: Context, track_index: int, folded: bool) -> str:
    """
    Set the fold state of a group track.
    
    Parameters:
    - track_index: The index of the track
    - folded: True to fold, False to unfold
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_fold_state", {
            "track_index": track_index,
            "folded": folded
        })
        if "error" in result: return f"Error: {result['error']}"
        state = "folded" if result.get("folded") else "unfolded"
        return f"Track {track_index} is now {state}"
    except Exception as e:
        return f"Error: {str(e)}"

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()
