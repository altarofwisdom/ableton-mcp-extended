# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()

        # Initialize comprehensive device/plugin cache
        self._device_cache = {
            # VST/AU Plugins
            "vst3_plugins": None,
            "vst_plugins": None,
            "au_plugins": None,

            # Native Ableton devices
            "instruments": None,
            "audio_effects": None,
            "midi_effects": None,

            # Max for Live devices
            "m4l_instruments": None,
            "m4l_audio_effects": None,
            "m4l_midi_effects": None,

            # Drum racks (samples excluded - too large)
            "drum_racks": None,

            # Cache metadata
            "last_updated": 0,
            "is_built": False,
            "is_building": False,
            "cache_version": "1.0"
        }

        # Set up cache file path
        self._cache_file_path = self._get_cache_file_path()

        # Load existing cache on startup
        self._load_cache_from_file()

        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        buffer = ''  # Changed from b'' to '' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except:
                        # If we can't send the error, the connection is probably dead
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except:
                pass
            self.log_message("Client handler stopped")
    
    def _process_command(self, command):
        """Process a command from the client and return a response"""
        command_type = command.get("type", "")
        params = command.get("params", {})
        
        # Initialize response
        response = {
            "status": "success",
            "result": {}
        }
        
        try:
            # Route the command to the appropriate handler
            if command_type == "get_session_info":
                response["result"] = self._get_session_info()
            elif command_type == "get_track_info":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_info(track_index)
            elif command_type == "explore_api":
                response["result"] = self._explore_api()
            # Commands that modify Live's state should be scheduled on the main thread
            elif command_type in ["create_midi_track", "create_audio_track", "set_track_name",
                                 "create_clip", "add_notes_to_clip", "set_clip_name",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "set_track_input_routing", "clear_clip", "delete_clip",
                                 "remove_notes_from_clip", "set_device_parameter", "delete_device",
                                 "set_clip_automation_step", "clear_clip_automation"]:
                # Use a thread-safe approach with a response queue
                response_queue = queue.Queue()
                
                # Define a function to execute on the main thread
                def main_thread_task():
                    try:
                        result = None
                        if command_type == "create_midi_track":
                            index = params.get("index", -1)
                            result = self._create_midi_track(index)
                        elif command_type == "create_audio_track":
                            index = params.get("index", -1)
                            result = self._create_audio_track(index)
                        elif command_type == "set_track_name":
                            track_index = params.get("track_index", 0)
                            name = params.get("name", "")
                            result = self._set_track_name(track_index, name)
                        elif command_type == "create_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            length = params.get("length", 4.0)
                            result = self._create_clip(track_index, clip_index, length)
                        elif command_type == "add_notes_to_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            notes = params.get("notes", [])
                            result = self._add_notes_to_clip(track_index, clip_index, notes)
                        elif command_type == "set_clip_name":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            name = params.get("name", "")
                            result = self._set_clip_name(track_index, clip_index, name)
                        elif command_type == "set_tempo":
                            tempo = params.get("tempo", 120.0)
                            result = self._set_tempo(tempo)
                        elif command_type == "fire_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._fire_clip(track_index, clip_index)
                        elif command_type == "stop_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._stop_clip(track_index, clip_index)
                        elif command_type == "start_playback":
                            result = self._start_playback()
                        elif command_type == "stop_playback":
                            result = self._stop_playback()
                        elif command_type == "load_instrument_or_effect":
                            track_index = params.get("track_index", 0)
                            uri = params.get("uri", "")
                            result = self._load_instrument_or_effect(track_index, uri)
                        elif command_type == "load_browser_item":
                            track_index = params.get("track_index", 0)
                            item_uri = params.get("item_uri", "")
                            result = self._load_browser_item(track_index, item_uri)
                        elif command_type == "set_track_input_routing":
                            track_index = params.get("track_index", 0)
                            routing_type = params.get("routing_type", "")
                            routing_channel = params.get("routing_channel", "")
                            result = self._set_track_input_routing(track_index, routing_type, routing_channel)
                        elif command_type == "clear_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._clear_clip(track_index, clip_index)
                        elif command_type == "delete_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._delete_clip(track_index, clip_index)
                        elif command_type == "remove_notes_from_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            notes_to_remove = params.get("notes_to_remove", [])
                            result = self._remove_notes_from_clip(track_index, clip_index, notes_to_remove)
                        elif command_type == "set_device_parameter":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            parameter_index = params.get("parameter_index", 0)
                            value = params.get("value", 0.0)
                            result = self._set_device_parameter(track_index, device_index, parameter_index, value)
                        elif command_type == "delete_device":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            result = self._delete_device(track_index, device_index)
                        elif command_type == "set_clip_automation_step":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            device_index = params.get("device_index", 0)
                            parameter_index = params.get("parameter_index", 0)
                            start_time = params.get("start_time", 0.0)
                            duration = params.get("duration", 1.0)
                            value = params.get("value", 0.0)
                            result = self._set_clip_automation_step(track_index, clip_index, device_index, parameter_index, start_time, duration, value)
                        elif command_type == "clear_clip_automation":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            device_index = params.get("device_index", 0)
                            parameter_index = params.get("parameter_index", 0)
                            result = self._clear_clip_automation(track_index, clip_index, device_index, parameter_index)
                        
                        # Put the result in the queue
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        self.log_message("Error in main thread task: " + str(e))
                        self.log_message(traceback.format_exc())
                        response_queue.put({"status": "error", "message": str(e)})
                
                # Schedule the task to run on the main thread
                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    # If we're already on the main thread, execute directly
                    main_thread_task()
                
                # Wait for the response with a timeout
                try:
                    task_response = response_queue.get(timeout=10.0)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for operation to complete"
            elif command_type == "get_browser_item":
                uri = params.get("uri", None)
                path = params.get("path", None)
                response["result"] = self._get_browser_item(uri, path)
            elif command_type == "get_browser_categories":
                category_type = params.get("category_type", "all")
                response["result"] = self._get_browser_categories(category_type)
            elif command_type == "get_browser_items":
                path = params.get("path", "")
                item_type = params.get("item_type", "all")
                response["result"] = self._get_browser_items(path, item_type)
            # Add the new browser commands
            elif command_type == "get_browser_tree":
                category_type = params.get("category_type", "all")
                response["result"] = self.get_browser_tree(category_type)
            elif command_type == "get_browser_items_at_path":
                path = params.get("path", "")
                response["result"] = self.get_browser_items_at_path(path)
            elif command_type == "get_audio_input_routings":
                response["result"] = self._get_audio_input_routings()
            elif command_type == "get_track_input_routings":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_input_routings(track_index)
            elif command_type == "get_device_parameters":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                response["result"] = self._get_device_parameters(track_index, device_index)
            elif command_type == "get_cached_devices":
                device_type = params.get("device_type", None)
                response["result"] = self._get_cached_devices(device_type)
            elif command_type == "refresh_device_cache":
                response["result"] = self._refresh_device_cache()
            elif command_type == "get_device_cache_status":
                response["result"] = self._get_device_cache_status()
            elif command_type == "clear_device_cache_file":
                self._clear_cache_file()
                # Also reset in-memory cache
                self._device_cache["is_built"] = False
                self._device_cache["last_updated"] = 0
                response["result"] = {"status": "Cache file cleared successfully"}
            elif command_type == "search_cached_devices":
                search_term = params.get("search_term", "")
                category = params.get("category", None)
                max_results = params.get("max_results", 50)
                response["result"] = self._search_cached_devices(search_term, category, max_results)
            elif command_type == "get_places":
                response["result"] = self._get_places()
            elif command_type == "browse_place":
                place_index = params.get("place_index", None)
                place_uri = params.get("place_uri", None)
                path = params.get("path", "")
                response["result"] = self._browse_place(place_index, place_uri, path)
            elif command_type == "explore_browser_structure":
                response["result"] = self._explore_browser_structure()
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)
        
        return response
    
    # Command implementations
    
    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": track.arm,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)

            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]

            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track at the specified index"""
        try:
            # Create the track
            self._song.create_audio_track(index)

            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]

            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise
    
    
    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise
    
    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            
            # Convert note data to Live's format
            live_notes = []
            for note in notes:
                pitch = note.get("pitch", 60)
                start_time = note.get("start_time", 0.0)
                duration = note.get("duration", 0.25)
                velocity = note.get("velocity", 100)
                mute = note.get("mute", False)
                
                live_notes.append((pitch, start_time, duration, velocity, mute))
            
            # Add the notes
            clip.set_notes(tuple(live_notes))
            
            result = {
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise
    
    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri):
        """Load a browser item onto a track by its URI"""
        try:
            self.log_message("Loading browser item: {0} on track {1}".format(item_uri, track_index))

            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            self.log_message("Target track: {0}".format(track.name))

            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")

            # Decode URL-encoded URI (e.g., %20 -> space)
            try:
                import urllib
                if hasattr(urllib, 'unquote'):
                    # Python 2
                    decoded_uri = urllib.unquote(item_uri)
                else:
                    # Python 3
                    from urllib.parse import unquote
                    decoded_uri = unquote(item_uri)
                self.log_message("Decoded URI: {0} -> {1}".format(item_uri, decoded_uri))
            except:
                decoded_uri = item_uri
                self.log_message("Could not decode URI, using original: {0}".format(item_uri))

            self.log_message("Starting URI search for: {0}".format(decoded_uri))

            # Find the browser item by URI (try both encoded and decoded)
            item = self._find_browser_item_by_uri(app.browser, decoded_uri)
            if not item:
                self.log_message("Decoded URI failed, trying original: {0}".format(item_uri))
                item = self._find_browser_item_by_uri(app.browser, item_uri)

            if not item:
                self.log_message("Browser item search failed for URI: {0}".format(item_uri))
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))

            self.log_message("Found browser item: {0}".format(item.name))

            # Select the track
            self._song.view.selected_track = track
            self.log_message("Selected track: {0}".format(track.name))

            # Load the item
            self.log_message("Loading item onto track...")
            app.browser.load_item(item)
            self.log_message("Item loaded successfully")

            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri'):
                item_uri = browser_or_item.uri
                # Try exact match first
                if item_uri == uri:
                    return browser_or_item

                # Try URL decoded comparison for encoded URIs
                try:
                    import urllib
                    if hasattr(urllib, 'unquote'):
                        # Python 2
                        decoded_item_uri = urllib.unquote(item_uri)
                        decoded_search_uri = urllib.unquote(uri)
                    else:
                        # Python 3
                        from urllib.parse import unquote
                        decoded_item_uri = unquote(item_uri)
                        decoded_search_uri = unquote(uri)

                    if decoded_item_uri == decoded_search_uri:
                        return browser_or_item

                    # Also try cross-comparison (encoded vs decoded)
                    if item_uri == decoded_search_uri or decoded_item_uri == uri:
                        return browser_or_item

                except:
                    pass
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories including plugins
                categories = []

                # Standard categories
                standard_cats = ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects']
                for cat_name in standard_cats:
                    if hasattr(browser_or_item, cat_name):
                        categories.append(getattr(browser_or_item, cat_name))

                # Check for plugin categories (discovered from API exploration)
                plugin_cats = ['plugins', 'vst', 'vst3', 'au', 'max_for_live']
                for cat_name in plugin_cats:
                    if hasattr(browser_or_item, cat_name):
                        categories.append(getattr(browser_or_item, cat_name))
                        self.log_message("Found plugin category: {0}".format(cat_name))

                for category in categories:
                    if category:  # Make sure category is not None
                        item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                        if item:
                            return item

                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _explore_api(self):
        """
        Comprehensive exploration of the Live API - dump ALL available methods and properties
        """
        try:
            result = {
                "song_all_methods": {},
                "song_callable_methods": {},
                "track_all_methods": {},
                "track_callable_methods": {},
                "master_track_methods": {},
                "return_track_methods": {},
                "application_methods": {},
                "browser_methods": {},
                "clip_methods": {},
                "device_methods": {}
            }

            self.log_message("=== COMPREHENSIVE API EXPLORATION ===")

            # Explore ALL song object methods and properties
            song_all = [m for m in dir(self._song) if not m.startswith('_')]
            self.log_message("=== ALL SONG METHODS/PROPERTIES ({0} total) ===".format(len(song_all)))

            for method in song_all:
                try:
                    method_obj = getattr(self._song, method)
                    method_info = {
                        "type": str(type(method_obj)),
                        "callable": callable(method_obj)
                    }
                    result["song_all_methods"][method] = method_info

                    if callable(method_obj):
                        result["song_callable_methods"][method] = method_info
                        self.log_message("SONG CALLABLE: {0} - {1}".format(method, method_info["type"]))
                    else:
                        self.log_message("SONG PROPERTY: {0} - {1}".format(method, method_info["type"]))

                except Exception as e:
                    self.log_message("ERROR inspecting song.{0}: {1}".format(method, str(e)))

            # Explore track object methods if tracks exist
            if len(self._song.tracks) > 0:
                track = self._song.tracks[0]
                track_all = [m for m in dir(track) if not m.startswith('_')]
                self.log_message("=== ALL TRACK METHODS/PROPERTIES ({0} total) ===".format(len(track_all)))

                for method in track_all:
                    try:
                        method_obj = getattr(track, method)
                        method_info = {
                            "type": str(type(method_obj)),
                            "callable": callable(method_obj)
                        }
                        result["track_all_methods"][method] = method_info

                        if callable(method_obj):
                            result["track_callable_methods"][method] = method_info
                            self.log_message("TRACK CALLABLE: {0} - {1}".format(method, method_info["type"]))

                    except Exception as e:
                        self.log_message("ERROR inspecting track.{0}: {1}".format(method, str(e)))

            # Explore master track
            master_track = self._song.master_track
            master_all = [m for m in dir(master_track) if not m.startswith('_')]
            self.log_message("=== MASTER TRACK METHODS ({0} total) ===".format(len(master_all)))

            for method in master_all[:20]:  # Limit output
                try:
                    method_obj = getattr(master_track, method)
                    if callable(method_obj):
                        result["master_track_methods"][method] = str(type(method_obj))
                        self.log_message("MASTER CALLABLE: {0}".format(method))
                except:
                    pass

            # Explore return tracks if they exist
            if len(self._song.return_tracks) > 0:
                return_track = self._song.return_tracks[0]
                return_all = [m for m in dir(return_track) if not m.startswith('_')]
                self.log_message("=== RETURN TRACK METHODS ({0} total) ===".format(len(return_all)))

                for method in return_all[:20]:  # Limit output
                    try:
                        method_obj = getattr(return_track, method)
                        if callable(method_obj):
                            result["return_track_methods"][method] = str(type(method_obj))
                            self.log_message("RETURN CALLABLE: {0}".format(method))
                    except:
                        pass

            # Explore application object
            try:
                app = self.application()
                if app:
                    app_all = [m for m in dir(app) if not m.startswith('_')]
                    self.log_message("=== APPLICATION METHODS ({0} total) ===".format(len(app_all)))

                    for method in app_all:
                        try:
                            method_obj = getattr(app, method)
                            if callable(method_obj):
                                result["application_methods"][method] = str(type(method_obj))
                                self.log_message("APP CALLABLE: {0}".format(method))
                        except:
                            pass
            except Exception as e:
                self.log_message("Could not explore application: {0}".format(str(e)))

            # Explore browser if available
            try:
                app = self.application()
                if app and hasattr(app, 'browser') and app.browser:
                    browser_all = [m for m in dir(app.browser) if not m.startswith('_')]
                    self.log_message("=== BROWSER METHODS ({0} total) ===".format(len(browser_all)))

                    for method in browser_all:
                        try:
                            method_obj = getattr(app.browser, method)
                            if callable(method_obj):
                                result["browser_methods"][method] = str(type(method_obj))
                                self.log_message("BROWSER CALLABLE: {0}".format(method))
                        except:
                            pass
            except Exception as e:
                self.log_message("Could not explore browser: {0}".format(str(e)))

            # Explore clip methods if any clips exist
            try:
                for track in self._song.tracks:
                    for slot in track.clip_slots:
                        if slot.has_clip:
                            clip = slot.clip
                            clip_all = [m for m in dir(clip) if not m.startswith('_')]
                            self.log_message("=== CLIP METHODS ({0} total) ===".format(len(clip_all)))

                            for method in clip_all[:20]:  # Limit output
                                try:
                                    method_obj = getattr(clip, method)
                                    if callable(method_obj):
                                        result["clip_methods"][method] = str(type(method_obj))
                                        self.log_message("CLIP CALLABLE: {0}".format(method))
                                except:
                                    pass
                            break
                    if result["clip_methods"]:
                        break
            except Exception as e:
                self.log_message("Could not explore clips: {0}".format(str(e)))

            # Explore device methods if any devices exist
            try:
                for track in self._song.tracks:
                    if len(track.devices) > 0:
                        device = track.devices[0]
                        device_all = [m for m in dir(device) if not m.startswith('_')]
                        self.log_message("=== DEVICE METHODS ({0} total) ===".format(len(device_all)))

                        for method in device_all[:20]:  # Limit output
                            try:
                                method_obj = getattr(device, method)
                                if callable(method_obj):
                                    result["device_methods"][method] = str(type(method_obj))
                                    self.log_message("DEVICE CALLABLE: {0}".format(method))
                            except:
                                pass
                        break
            except Exception as e:
                self.log_message("Could not explore devices: {0}".format(str(e)))

            self.log_message("=== COMPREHENSIVE API EXPLORATION COMPLETE ===")
            self.log_message("Total song methods: {0}".format(len(result["song_all_methods"])))
            self.log_message("Total song callables: {0}".format(len(result["song_callable_methods"])))
            self.log_message("Total track methods: {0}".format(len(result["track_all_methods"])))
            self.log_message("Total track callables: {0}".format(len(result["track_callable_methods"])))

            return result

        except Exception as e:
            self.log_message("Error during comprehensive API exploration: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            return {"error": str(e)}

    def _get_audio_input_routings(self):
        """Get available audio input routings for the current audio interface"""
        try:
            # Look at the first audio track to get available input routings
            audio_tracks = [track for track in self._song.tracks if track.has_audio_input]

            if not audio_tracks:
                return {
                    "error": "No audio tracks found. Create an audio track first.",
                    "available_types": [],
                    "available_channels": {}
                }

            track = audio_tracks[0]

            result = {
                "available_routing_types": [],
                "available_channels": {},
                "current_routing": {}
            }

            # Get available input routing types
            if hasattr(track, 'available_input_routing_types'):
                routing_types = list(track.available_input_routing_types)
                result["available_routing_types"] = [str(rt) for rt in routing_types]

                # For each routing type, get available channels
                for routing_type in routing_types:
                    try:
                        # Temporarily set the routing type to get available channels
                        original_routing = track.current_input_routing
                        track.current_input_routing = routing_type

                        if hasattr(track, 'available_input_routing_channels'):
                            channels = list(track.available_input_routing_channels)
                            result["available_channels"][str(routing_type)] = [str(ch) for ch in channels]

                        # Restore original routing
                        track.current_input_routing = original_routing
                    except Exception as e:
                        self.log_message("Error getting channels for routing type {0}: {1}".format(str(routing_type), str(e)))
                        result["available_channels"][str(routing_type)] = []

            # Get current routing info
            if hasattr(track, 'current_input_routing'):
                result["current_routing"]["type"] = str(track.current_input_routing)

            if hasattr(track, 'input_routing_channel'):
                result["current_routing"]["channel"] = str(track.input_routing_channel)

            return result

        except Exception as e:
            self.log_message("Error getting audio input routings: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            return {"error": str(e)}

    def _get_track_input_routings(self, track_index):
        """Get input routing information for a specific track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if not track.has_audio_input:
                return {
                    "error": "Track is not an audio track",
                    "track_name": track.name,
                    "is_audio_track": False
                }

            result = {
                "track_index": track_index,
                "track_name": track.name,
                "is_audio_track": True,
                "available_routing_types": [],
                "available_channels": [],
                "current_routing": {}
            }

            # Get available input routing types for this track
            if hasattr(track, 'available_input_routing_types'):
                routing_types = list(track.available_input_routing_types)
                result["available_routing_types"] = [str(rt) for rt in routing_types]

            # Get available input channels for current routing type
            if hasattr(track, 'available_input_routing_channels'):
                channels = list(track.available_input_routing_channels)
                result["available_channels"] = [str(ch) for ch in channels]

            # Get current input routing
            if hasattr(track, 'current_input_routing'):
                result["current_routing"]["type"] = str(track.current_input_routing)

            if hasattr(track, 'input_routing_channel'):
                result["current_routing"]["channel"] = str(track.input_routing_channel)

            # Get input routing details if available
            if hasattr(track, 'input_routings'):
                result["all_input_routings"] = [str(r) for r in track.input_routings]

            if hasattr(track, 'input_sub_routings'):
                result["input_sub_routings"] = [str(r) for r in track.input_sub_routings]

            return result

        except Exception as e:
            self.log_message("Error getting track input routings: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            return {"error": str(e)}

    def _set_track_input_routing(self, track_index, routing_type, routing_channel):
        """Set input routing for a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if not track.has_audio_input:
                raise ValueError("Track is not an audio track")

            result = {
                "track_index": track_index,
                "track_name": track.name,
                "success": False
            }

            # Set the routing type if provided
            if routing_type and hasattr(track, 'current_input_routing'):
                # Find the routing type object
                available_types = list(track.available_input_routing_types)
                routing_obj = None

                for rt in available_types:
                    if str(rt) == routing_type:
                        routing_obj = rt
                        break

                if routing_obj:
                    track.current_input_routing = routing_obj
                    result["routing_type_set"] = str(routing_obj)
                else:
                    raise ValueError("Routing type '{0}' not found in available types: {1}".format(
                        routing_type, [str(rt) for rt in available_types]))

            # Set the routing channel if provided
            if routing_channel and hasattr(track, 'input_routing_channel'):
                # Find the channel object
                available_channels = list(track.available_input_routing_channels)
                channel_obj = None

                self.log_message("Looking for routing channel: '{0}'".format(routing_channel))
                self.log_message("Available channels: {0}".format([str(ch) for ch in available_channels]))

                # Try exact match first
                for ch in available_channels:
                    if str(ch) == routing_channel:
                        channel_obj = ch
                        break

                # If exact match fails, try partial match (for named channels like "3/4 Digitakt")
                if not channel_obj:
                    for ch in available_channels:
                        if routing_channel in str(ch) or str(ch).startswith(routing_channel):
                            channel_obj = ch
                            self.log_message("Found partial match: '{0}' for '{1}'".format(str(ch), routing_channel))
                            break

                if channel_obj:
                    track.input_routing_channel = channel_obj
                    result["routing_channel_set"] = str(channel_obj)
                    self.log_message("Successfully set routing channel to: '{0}'".format(str(channel_obj)))
                else:
                    available_list = [str(ch) for ch in available_channels]
                    self.log_message("Channel not found. Available: {0}".format(available_list))
                    raise ValueError("Routing channel '{0}' not found in available channels: {1}".format(
                        routing_channel, available_list))

            result["success"] = True

            # Return current state
            if hasattr(track, 'current_input_routing'):
                result["current_routing_type"] = str(track.current_input_routing)

            if hasattr(track, 'input_routing_channel'):
                result["current_routing_channel"] = str(track.input_routing_channel)

            return result

        except Exception as e:
            self.log_message("Error setting track input routing: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _get_device_parameters(self, track_index, device_index):
        """Get detailed information about a device's parameters"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(track_index, len(self._song.tracks) - 1))

            track = self._song.tracks[track_index]

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index {0} out of range (0-{1})".format(device_index, len(track.devices) - 1))

            device = track.devices[device_index]

            # Get device info
            device_info = {
                "name": device.name,
                "class_name": device.class_name,
                "can_have_chains": device.can_have_chains,
                "can_have_drum_pads": device.can_have_drum_pads,
                "parameters": []
            }

            # Get all parameters
            for i, param in enumerate(device.parameters):
                param_info = {
                    "index": i,
                    "name": param.name,
                    "display_name": param.original_name,
                    "value": param.value,
                    "min": param.min,
                    "max": param.max,
                    "is_enabled": param.is_enabled,
                    "is_quantized": param.is_quantized,
                    "value_items": []
                }

                # Get quantized value items if available
                if param.is_quantized and hasattr(param, 'value_items'):
                    param_info["value_items"] = list(param.value_items)

                # Add string representation of current value
                try:
                    param_info["str_value"] = str(param)
                except:
                    param_info["str_value"] = "N/A"

                device_info["parameters"].append(param_info)

            return device_info

        except Exception as e:
            self.log_message("Error getting device parameters: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _set_device_parameter(self, track_index, device_index, parameter_index, value):
        """Set a device parameter value"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(track_index, len(self._song.tracks) - 1))

            track = self._song.tracks[track_index]

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index {0} out of range (0-{1})".format(device_index, len(track.devices) - 1))

            device = track.devices[device_index]

            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index {0} out of range (0-{1})".format(parameter_index, len(device.parameters) - 1))

            param = device.parameters[parameter_index]

            # Store original value for comparison
            original_value = param.value

            # Clamp value to parameter range
            clamped_value = max(param.min, min(param.max, float(value)))

            # Set the parameter value
            param.value = clamped_value

            result = {
                "device_name": device.name,
                "parameter_name": param.name,
                "original_value": original_value,
                "requested_value": value,
                "actual_value": param.value,
                "min": param.min,
                "max": param.max,
                "success": True
            }

            return result

        except Exception as e:
            self.log_message("Error setting device parameter: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _clear_clip(self, track_index, clip_index):
        """Clear all notes from a clip without deleting the clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise ValueError("No clip found at slot {0}".format(clip_index))

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise ValueError("Can only clear notes from MIDI clips")

            # Remove all notes from the clip
            clip.remove_notes(0, 0, clip.length, 127)

            result = {
                "track_name": track.name,
                "clip_name": clip.name,
                "clip_length": clip.length,
                "cleared": True
            }

            return result

        except Exception as e:
            self.log_message("Error clearing clip: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _delete_clip(self, track_index, clip_index):
        """Delete a clip from its slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise ValueError("No clip found at slot {0}".format(clip_index))

            clip_name = clip_slot.clip.name

            # Delete the clip
            clip_slot.delete_clip()

            result = {
                "track_name": track.name,
                "clip_name": clip_name,
                "clip_index": clip_index,
                "deleted": True
            }

            return result

        except Exception as e:
            self.log_message("Error deleting clip: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _remove_notes_from_clip(self, track_index, clip_index, notes_to_remove):
        """Remove specific notes from a clip based on criteria"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise ValueError("No clip found at slot {0}".format(clip_index))

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise ValueError("Can only remove notes from MIDI clips")

            removed_count = 0

            # Process each note removal criterion
            for note_criteria in notes_to_remove:
                pitch = note_criteria.get("pitch", None)
                start_time = note_criteria.get("start_time", None)
                velocity = note_criteria.get("velocity", None)
                duration = note_criteria.get("duration", None)

                # Get all notes in the clip
                notes = clip.get_notes(0, 0, clip.length, 127)

                notes_to_remove_list = []

                for note in notes:
                    should_remove = True

                    # Check each criterion
                    if pitch is not None and note.pitch != pitch:
                        should_remove = False
                    if start_time is not None and abs(note.start_time - start_time) > 0.001:
                        should_remove = False
                    if velocity is not None and note.velocity != velocity:
                        should_remove = False
                    if duration is not None and abs(note.duration - duration) > 0.001:
                        should_remove = False

                    if should_remove:
                        notes_to_remove_list.append(note)

                # Remove the matching notes
                if notes_to_remove_list:
                    clip.remove_notes_extended(notes_to_remove_list)
                    removed_count += len(notes_to_remove_list)

            result = {
                "track_name": track.name,
                "clip_name": clip.name,
                "removed_count": removed_count,
                "criteria_count": len(notes_to_remove)
            }

            return result

        except Exception as e:
            self.log_message("Error removing notes from clip: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _delete_device(self, track_index, device_index):
        """Delete a device from a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")

            device = track.devices[device_index]
            device_name = device.name
            device_class = device.class_name

            # Delete the device using the track's delete_device method
            track.delete_device(device_index)

            result = {
                "track_name": track.name,
                "track_index": track_index,
                "device_name": device_name,
                "device_class": device_class,
                "device_index": device_index,
                "deleted": True,
                "remaining_devices": len(track.devices)
            }

            self.log_message("Deleted device '{0}' from track '{1}'".format(device_name, track.name))

            return result

        except Exception as e:
            self.log_message("Error deleting device: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _set_clip_automation_step(self, track_index, clip_index, device_index, parameter_index, start_time, duration, value):
        """Insert a stepped automation segment into a clip envelope for a device parameter."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(track_index, len(self._song.tracks) - 1))

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index {0} out of range (0-{1})".format(clip_index, len(track.clip_slots) - 1))
            
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise ValueError("No clip found at track {0}, slot {1}".format(track_index, clip_index))

            clip = clip_slot.clip

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index {0} out of range (0-{1})".format(device_index, len(track.devices) - 1))

            device = track.devices[device_index]

            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index {0} out of range (0-{1})".format(parameter_index, len(device.parameters) - 1))

            parameter = device.parameters[parameter_index]

            envelope = clip.automation_envelope(parameter)
            if envelope is None:
                raise ValueError("Could not get automation envelope for parameter '{0}'".format(parameter.name))

            envelope.insert_step(start_time, duration, value)

            self.log_message("Set automation step for parameter '{0}' in clip at track {1}, slot {2}".format(
                parameter.name, track_index, clip_index))

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter_name": parameter.name,
                "start_time": start_time,
                "duration": duration,
                "value": value,
                "status": "success"
            }

        except Exception as e:
            self.log_message("Error setting clip automation step: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _clear_clip_automation(self, track_index, clip_index, device_index, parameter_index):
        """Clear clip automation envelope data for a single device parameter."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(track_index, len(self._song.tracks) - 1))

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index {0} out of range (0-{1})".format(clip_index, len(track.clip_slots) - 1))
            
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise ValueError("No clip found at track {0}, slot {1}".format(track_index, clip_index))

            clip = clip_slot.clip

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index {0} out of range (0-{1})".format(device_index, len(track.devices) - 1))

            device = track.devices[device_index]

            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index {0} out of range (0-{1})".format(parameter_index, len(device.parameters) - 1))

            parameter = device.parameters[parameter_index]

            clip.clear_envelope(parameter)

            self.log_message("Cleared automation for parameter '{0}' in clip at track {1}, slot {2}".format(
                parameter.name, track_index, clip_index))

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter_name": parameter.name,
                "status": "success"
            }

        except Exception as e:
            self.log_message("Error clearing clip automation: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _is_cache_built(self):
        """Check if the device cache has been built"""
        return self._device_cache["is_built"] and not self._device_cache["is_building"]

    def _build_device_cache(self):
        """Build comprehensive cache of all available devices and plugins"""
        if self._device_cache["is_building"]:
            return self._device_cache

        try:
            import time
            self._device_cache["is_building"] = True
            self.log_message("Building comprehensive device cache...")

            app = self.application()
            if not app or not app.browser:
                return self._device_cache

            browser = app.browser

            # Cache VST3 plugins
            if hasattr(browser, 'plugins'):
                self._device_cache["vst3_plugins"] = self._extract_browser_items(browser.plugins, "VST3")
                self._device_cache["vst_plugins"] = self._extract_browser_items(browser.plugins, "VST")
                self._device_cache["au_plugins"] = self._extract_browser_items(browser.plugins, "AU")

            # Cache native instruments
            if hasattr(browser, 'instruments'):
                self._device_cache["instruments"] = self._extract_browser_items(browser.instruments, "Instruments")

            # Cache audio effects
            if hasattr(browser, 'audio_effects'):
                self._device_cache["audio_effects"] = self._extract_browser_items(browser.audio_effects, "Audio Effects")

            # Cache MIDI effects
            if hasattr(browser, 'midi_effects'):
                self._device_cache["midi_effects"] = self._extract_browser_items(browser.midi_effects, "MIDI Effects")

            # Cache Max for Live devices
            if hasattr(browser, 'max_for_live'):
                m4l_devices = self._extract_browser_items(browser.max_for_live, "Max for Live")
                # Separate M4L by type
                self._device_cache["m4l_instruments"] = [d for d in m4l_devices if "instrument" in d.get("path", "").lower()]
                self._device_cache["m4l_audio_effects"] = [d for d in m4l_devices if "audio" in d.get("path", "").lower()]
                self._device_cache["m4l_midi_effects"] = [d for d in m4l_devices if "midi" in d.get("path", "").lower()]

            # Cache drum racks only (samples excluded - too large)
            if hasattr(browser, 'drums'):
                self._device_cache["drum_racks"] = self._extract_browser_items(browser.drums, "Drums")

            # Update cache status
            self._device_cache["last_updated"] = time.time()
            self._device_cache["is_built"] = True
            self._device_cache["is_building"] = False

            self.log_message("Device cache built successfully:")
            for key, value in self._device_cache.items():
                if isinstance(value, list):
                    self.log_message("  {0}: {1} items".format(key, len(value)))

            # Save cache to file
            self._save_cache_to_file()

            return self._device_cache

        except Exception as e:
            self._device_cache["is_building"] = False
            self.log_message("Error building device cache: {0}".format(str(e)))
            return self._device_cache

    def _extract_browser_items(self, browser_category, category_type, max_depth=3):
        """Recursively extract all items from a browser category"""
        items = []
        try:
            def extract_recursive(item, current_path="", depth=0):
                if depth > max_depth:
                    return

                try:
                    if hasattr(item, 'children') and item.children:
                        # This is a folder
                        for child in item.children:
                            child_path = "{0}/{1}".format(current_path, child.name) if current_path else child.name
                            extract_recursive(child, child_path, depth + 1)
                    elif hasattr(item, 'is_loadable') and item.is_loadable:
                        # This is a loadable item
                        item_info = {
                            "name": item.name,
                            "path": current_path,
                            "uri": item.uri if hasattr(item, 'uri') else None,
                            "is_device": item.is_device if hasattr(item, 'is_device') else False,
                            "category": category_type
                        }
                        items.append(item_info)
                except Exception as e:
                    self.log_message("Error extracting item {0}: {1}".format(getattr(item, 'name', 'unknown'), str(e)))

            # Start extraction
            if hasattr(browser_category, 'children'):
                for child in browser_category.children:
                    extract_recursive(child, child.name)
            else:
                extract_recursive(browser_category)

        except Exception as e:
            self.log_message("Error extracting {0}: {1}".format(category_type, str(e)))

        return items

    def _get_cached_devices(self, device_type=None):
        """Get devices from cache, building if necessary"""
        # Build cache if not built yet
        if not self._is_cache_built():
            self._build_device_cache()

        if device_type:
            return self._device_cache.get(device_type, [])
        else:
            # Return all cached devices
            result = {}
            for key, value in self._device_cache.items():
                if isinstance(value, list):
                    result[key] = value
            return result

    def _refresh_device_cache(self):
        """Force refresh of the device cache"""
        self._device_cache["is_built"] = False
        self._device_cache["last_updated"] = 0
        return self._build_device_cache()

    def _get_device_cache_status(self):
        """Get status information about the device cache"""
        import time
        current_time = time.time()

        status = {
            "is_built": self._device_cache["is_built"],
            "is_building": self._device_cache["is_building"],
            "last_updated": self._device_cache["last_updated"],
            "age_seconds": current_time - self._device_cache["last_updated"] if self._device_cache["last_updated"] > 0 else -1,
            "cached_categories": {}
        }

        # Count items in each category
        for key, value in self._device_cache.items():
            if isinstance(value, list):
                status["cached_categories"][key] = len(value)

        return status

    def _get_cache_file_path(self):
        """Get the path for the device cache file"""
        try:
            import os

            # Use Ableton's preferences directory
            home_dir = os.path.expanduser("~")
            cache_dir = os.path.join(home_dir, "Library", "Preferences", "Ableton", "Live 12.2", "AbletonMCP")

            # Create directory if it doesn't exist
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
                self.log_message("Created cache directory: {0}".format(cache_dir))

            cache_file = os.path.join(cache_dir, "device_cache.json")
            self.log_message("Cache file path: {0}".format(cache_file))
            return cache_file

        except Exception as e:
            self.log_message("Error setting up cache file path: {0}".format(str(e)))
            return None

    def _load_cache_from_file(self):
        """Load device cache from file if it exists"""
        if not self._cache_file_path:
            return

        try:
            import os
            import json

            if os.path.exists(self._cache_file_path):
                with open(self._cache_file_path, 'r') as f:
                    cached_data = json.load(f)

                # Verify cache version compatibility
                if cached_data.get("cache_version") == self._device_cache["cache_version"]:
                    # Update our cache with loaded data
                    for key, value in cached_data.items():
                        if key in self._device_cache:
                            self._device_cache[key] = value

                    self.log_message("Loaded device cache from file: {0} categories".format(
                        len([k for k, v in self._device_cache.items() if isinstance(v, list)])))
                    self.log_message("Cache age: {0}".format(
                        self._device_cache.get("last_updated", "unknown")))
                else:
                    self.log_message("Cache version mismatch, will rebuild")

            else:
                self.log_message("No existing cache file found")

        except Exception as e:
            self.log_message("Error loading cache from file: {0}".format(str(e)))

    def _save_cache_to_file(self):
        """Save device cache to file"""
        if not self._cache_file_path:
            return

        try:
            import json

            # Only save if cache is built
            if self._device_cache["is_built"]:
                with open(self._cache_file_path, 'w') as f:
                    json.dump(self._device_cache, f, indent=2)

                self.log_message("Saved device cache to file: {0}".format(self._cache_file_path))
            else:
                self.log_message("Cache not built yet, skipping save")

        except Exception as e:
            self.log_message("Error saving cache to file: {0}".format(str(e)))

    def _clear_cache_file(self):
        """Delete the cache file"""
        if not self._cache_file_path:
            return

        try:
            import os

            if os.path.exists(self._cache_file_path):
                os.remove(self._cache_file_path)
                self.log_message("Deleted cache file: {0}".format(self._cache_file_path))
            else:
                self.log_message("Cache file does not exist")

        except Exception as e:
            self.log_message("Error deleting cache file: {0}".format(str(e)))

    def _search_cached_devices(self, search_term, category=None, max_results=50):
        """
        Search for devices in the cache by name with fuzzy matching.

        Args:
            search_term: The term to search for (case-insensitive)
            category: Optional category to restrict search (e.g., "vst3_plugins", "instruments")
            max_results: Maximum number of results to return

        Returns:
            List of matching devices with their URIs and metadata
        """
        if not self._device_cache["is_built"]:
            return {"error": "Device cache not built. Please build cache first."}

        try:
            search_term = search_term.lower()
            results = []

            # Define which categories to search
            search_categories = []
            if category:
                if category in self._device_cache and isinstance(self._device_cache[category], list):
                    search_categories = [category]
                else:
                    return {"error": "Invalid category: {0}".format(category)}
            else:
                # Search all categories
                search_categories = [
                    "vst3_plugins", "vst_plugins", "au_plugins",
                    "instruments", "audio_effects", "midi_effects",
                    "m4l_instruments", "m4l_audio_effects", "m4l_midi_effects",
                    "drum_racks"
                ]

            # Search through specified categories
            for cat in search_categories:
                if cat in self._device_cache and isinstance(self._device_cache[cat], list):
                    for device in self._device_cache[cat]:
                        if not device or not isinstance(device, dict):
                            continue

                        device_name = device.get("name", "").lower()
                        device_path = device.get("path", "").lower()

                        # Check for exact match, substring match, or word match
                        if (search_term in device_name or
                            search_term in device_path or
                            any(search_term in word for word in device_name.split()) or
                            any(search_term in word for word in device_path.split())):

                            result = {
                                "name": device.get("name", ""),
                                "uri": device.get("uri", ""),
                                "path": device.get("path", ""),
                                "category": cat,
                                "is_loadable": device.get("is_loadable", False)
                            }

                            # Calculate relevance score for better sorting
                            score = 0
                            if search_term == device_name:
                                score = 100  # Exact match
                            elif device_name.startswith(search_term):
                                score = 90   # Starts with
                            elif search_term in device_name:
                                score = 80   # Contains
                            elif any(word.startswith(search_term) for word in device_name.split()):
                                score = 70   # Word starts with
                            elif search_term in device_path:
                                score = 60   # In path
                            else:
                                score = 50   # Other matches

                            result["relevance_score"] = score
                            results.append(result)

            # Sort by relevance score (highest first)
            results.sort(key=lambda x: x["relevance_score"], reverse=True)

            # Limit results
            if len(results) > max_results:
                results = results[:max_results]

            return {
                "search_term": search_term,
                "category": category,
                "total_results": len(results),
                "results": results
            }

        except Exception as e:
            self.log_message("Error searching cached devices: {0}".format(str(e)))
            return {"error": "Search failed: {0}".format(str(e))}

    def _get_places(self):
        """Get the list of Places (user-added folders) from the browser"""
        try:
            app = self.application()
            if not app or not app.browser:
                return {"error": "Browser not available"}

            browser = app.browser
            places_info = {
                "available_attributes": [],
                "places": []
            }

            # First, let's see what attributes are available on the browser
            browser_attrs = [attr for attr in dir(browser) if not attr.startswith('_')]
            places_info["browser_attributes"] = browser_attrs

            # Look for places/user library related attributes
            places_attrs = [attr for attr in browser_attrs if 'place' in attr.lower() or 'user' in attr.lower() or 'library' in attr.lower()]
            places_info["places_related_attributes"] = places_attrs

            # Try to access common places attributes
            if hasattr(browser, 'user_library'):
                try:
                    user_lib = browser.user_library
                    places_info["user_library"] = {
                        "available": True,
                        "type": str(type(user_lib)),
                        "attributes": [attr for attr in dir(user_lib) if not attr.startswith('_')]
                    }

                    # Try to get children if available
                    if hasattr(user_lib, 'children'):
                        places_info["user_library"]["has_children"] = True
                        try:
                            children = list(user_lib.children)
                            places_info["user_library"]["children_count"] = len(children)

                            # Get info about first few places
                            for i, child in enumerate(children[:5]):
                                place_info = {
                                    "index": i,
                                    "name": getattr(child, 'name', 'Unknown'),
                                    "uri": getattr(child, 'uri', ''),
                                    "is_folder": getattr(child, 'is_folder', False),
                                    "attributes": [attr for attr in dir(child) if not attr.startswith('_')]
                                }
                                places_info["places"].append(place_info)
                        except Exception as e:
                            places_info["user_library"]["children_error"] = str(e)
                    else:
                        places_info["user_library"]["has_children"] = False

                except Exception as e:
                    places_info["user_library"] = {"error": str(e)}
            else:
                places_info["user_library"] = {"available": False}

            # Try other possible places attributes
            for attr_name in ['places', 'user_folders', 'user_places']:
                if hasattr(browser, attr_name):
                    try:
                        attr_obj = getattr(browser, attr_name)
                        places_info[attr_name] = {
                            "available": True,
                            "type": str(type(attr_obj)),
                            "attributes": [attr for attr in dir(attr_obj) if not attr.startswith('_')]
                        }
                    except Exception as e:
                        places_info[attr_name] = {"error": str(e)}

            return places_info

        except Exception as e:
            self.log_message("Error getting places: {0}".format(str(e)))
            return {"error": "Failed to get places: {0}".format(str(e))}

    def _browse_place(self, place_index=None, place_uri=None, path=""):
        """Browse the contents of a specific place by index or URI"""
        try:
            app = self.application()
            if not app or not app.browser:
                return {"error": "Browser not available"}

            browser = app.browser

            # Get the target place
            target_place = None

            if place_uri:
                # Try to find by URI using the existing function
                target_place = self._find_browser_item_by_uri(browser, place_uri)
            elif place_index is not None:
                # Try to get by index from user_library
                if hasattr(browser, 'user_library') and hasattr(browser.user_library, 'children'):
                    try:
                        children = list(browser.user_library.children)
                        if 0 <= place_index < len(children):
                            target_place = children[place_index]
                    except Exception as e:
                        return {"error": "Failed to access place by index: {0}".format(str(e))}

            if not target_place:
                return {"error": "Place not found"}

            # Now browse the contents
            result = {
                "place_name": getattr(target_place, 'name', 'Unknown'),
                "place_uri": getattr(target_place, 'uri', ''),
                "current_path": path,
                "contents": []
            }

            # Navigate to the specified path if provided
            current_item = target_place
            if path:
                path_parts = [p for p in path.split('/') if p]
                for part in path_parts:
                    if hasattr(current_item, 'children'):
                        found = False
                        for child in current_item.children:
                            if getattr(child, 'name', '') == part:
                                current_item = child
                                found = True
                                break
                        if not found:
                            return {"error": "Path not found: {0}".format(part)}
                    else:
                        return {"error": "Cannot navigate deeper - not a folder"}

            # Get contents of current location
            if hasattr(current_item, 'children'):
                try:
                    for child in current_item.children:
                        item_info = {
                            "name": getattr(child, 'name', 'Unknown'),
                            "uri": getattr(child, 'uri', ''),
                            "is_folder": getattr(child, 'is_folder', False),
                            "is_device": getattr(child, 'is_device', False),
                            "is_loadable": getattr(child, 'is_loadable', False),
                            "is_preview": getattr(child, 'is_preview', False)
                        }

                        # Try to get file type info
                        if hasattr(child, 'source') and hasattr(child.source, 'can_have_signature'):
                            item_info["source_info"] = {
                                "can_have_signature": child.source.can_have_signature
                            }

                        result["contents"].append(item_info)

                except Exception as e:
                    result["browse_error"] = str(e)
            else:
                result["contents"] = []
                result["note"] = "This item has no children to browse"

            result["total_items"] = len(result["contents"])
            return result

        except Exception as e:
            self.log_message("Error browsing place: {0}".format(str(e)))
            return {"error": "Failed to browse place: {0}".format(str(e))}

    def _explore_browser_structure(self):
        """Comprehensive exploration of browser structure to find user folders"""
        try:
            app = self.application()
            if not app or not app.browser:
                return {"error": "Browser not available"}

            browser = app.browser
            exploration = {
                "browser_attributes": [],
                "detailed_exploration": {}
            }

            # Get all browser attributes
            browser_attrs = [attr for attr in dir(browser) if not attr.startswith('_')]
            exploration["browser_attributes"] = browser_attrs

            # Explore each major browser section
            sections_to_explore = [
                'user_library', 'places', 'user_folders', 'user_places',
                'library', 'folders', 'samples', 'instruments', 'audio_effects',
                'midi_effects', 'drums', 'sounds', 'plugins', 'max_for_live'
            ]

            for section_name in sections_to_explore:
                if hasattr(browser, section_name):
                    try:
                        section = getattr(browser, section_name)
                        section_info = {
                            "exists": True,
                            "type": str(type(section)),
                            "attributes": [attr for attr in dir(section) if not attr.startswith('_')],
                            "has_children": hasattr(section, 'children'),
                            "children_info": []
                        }

                        # Try to get children information
                        if hasattr(section, 'children'):
                            try:
                                children = list(section.children)
                                section_info["children_count"] = len(children)

                                # Get detailed info about first few children
                                for i, child in enumerate(children[:10]):
                                    child_info = {
                                        "index": i,
                                        "name": getattr(child, 'name', 'Unknown'),
                                        "type": str(type(child)),
                                        "uri": getattr(child, 'uri', ''),
                                        "is_folder": getattr(child, 'is_folder', False),
                                        "is_device": getattr(child, 'is_device', False),
                                        "is_loadable": getattr(child, 'is_loadable', False),
                                        "has_children": hasattr(child, 'children'),
                                        "attributes": [attr for attr in dir(child) if not attr.startswith('_')][:15]  # Limit to first 15
                                    }

                                    # If this child has children, get a sample
                                    if hasattr(child, 'children'):
                                        try:
                                            grandchildren = list(child.children)
                                            child_info["children_count"] = len(grandchildren)
                                            if grandchildren:
                                                first_grandchild = grandchildren[0]
                                                child_info["sample_grandchild"] = {
                                                    "name": getattr(first_grandchild, 'name', 'Unknown'),
                                                    "is_folder": getattr(first_grandchild, 'is_folder', False),
                                                    "uri": getattr(first_grandchild, 'uri', '')
                                                }
                                        except Exception as e:
                                            child_info["children_error"] = str(e)

                                    section_info["children_info"].append(child_info)

                            except Exception as e:
                                section_info["children_error"] = str(e)

                        # Try to get other useful properties
                        for prop in ['name', 'uri', 'is_folder', 'is_loadable']:
                            if hasattr(section, prop):
                                try:
                                    section_info[prop] = getattr(section, prop)
                                except:
                                    pass

                        exploration["detailed_exploration"][section_name] = section_info

                    except Exception as e:
                        exploration["detailed_exploration"][section_name] = {
                            "exists": True,
                            "error": str(e)
                        }
                else:
                    exploration["detailed_exploration"][section_name] = {"exists": False}

            # Also try some additional patterns that might exist
            additional_patterns = []
            for attr in browser_attrs:
                if any(keyword in attr.lower() for keyword in ['user', 'place', 'folder', 'custom', 'added']):
                    additional_patterns.append(attr)

            exploration["additional_user_related_attributes"] = additional_patterns

            # Try to access these additional patterns
            for pattern in additional_patterns[:5]:  # Limit to first 5 to avoid too much data
                if pattern not in exploration["detailed_exploration"]:
                    try:
                        obj = getattr(browser, pattern)
                        exploration["detailed_exploration"][pattern] = {
                            "type": str(type(obj)),
                            "has_children": hasattr(obj, 'children'),
                            "attributes": [attr for attr in dir(obj) if not attr.startswith('_')][:10]
                        }
                    except Exception as e:
                        exploration["detailed_exploration"][pattern] = {"error": str(e)}

            return exploration

        except Exception as e:
            self.log_message("Error exploring browser structure: {0}".format(str(e)))
            return {"error": "Failed to explore browser: {0}".format(str(e))}
