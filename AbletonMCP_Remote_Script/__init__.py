# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import os
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
HOST = "127.0.0.1"
MAX_REQUEST_BYTES = 4 * 1024 * 1024

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

                    if len(buffer.encode('utf-8')) > MAX_REQUEST_BYTES:
                        raise RuntimeError("Request exceeded maximum allowed size")
                    
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
            # Commands that modify Live's state should be scheduled on the main thread
            elif command_type in ["create_midi_track", "set_track_name",
                                 "create_clip", "create_audio_clip", "add_notes_to_clip", "set_clip_name",
                                 "delete_clip", "clear_clip_notes", "load_sample_to_drum_pad",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 # Session reorg / mixing (local fork additions)
                                 "delete_track", "create_scene", "set_scene_name",
                                 "duplicate_clip_to_scene", "set_track_color",
                                 "set_track_monitor", "set_track_arm", "set_track_volume",
                                 "set_device_parameter",
                                 # Surgical note editing / clip properties (local fork additions)
                                 "remove_notes_in_range", "update_notes",
                                 "set_clip_loop", "quantize_clip",
                                 "bounce_midi_clip_to_audio",
                                 # Arrangement view – must run on the main thread
                                 "switch_to_arrangement_view", "set_current_song_time",
                                 "duplicate_session_clip_to_arrangement",
                                 # Feedback-loop tools (local fork additions)
                                 "undo", "redo",
                                 "set_track_pan", "set_track_mute", "set_track_solo",
                                 "set_send_level",
                                 # Track creation (local fork additions)
                                 "create_audio_track", "create_return_track"]:
                # Use a thread-safe approach with a response queue
                response_queue = queue.Queue()
                
                # Define a function to execute on the main thread
                def main_thread_task():
                    try:
                        result = None
                        if command_type == "create_midi_track":
                            index = params.get("index", -1)
                            result = self._create_midi_track(index)
                        elif command_type == "set_track_name":
                            track_index = params.get("track_index", 0)
                            name = params.get("name", "")
                            result = self._set_track_name(track_index, name)
                        elif command_type == "create_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            length = params.get("length", 4.0)
                            result = self._create_clip(track_index, clip_index, length)
                        elif command_type == "create_audio_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            path = params.get("path", "")
                            result = self._create_audio_clip(track_index, clip_index, path)
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
                        elif command_type == "delete_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._delete_clip(track_index, clip_index)
                        elif command_type == "clear_clip_notes":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._clear_clip_notes(track_index, clip_index)
                        elif command_type == "load_sample_to_drum_pad":
                            track_index = params.get("track_index", 0)
                            pad_note = params.get("pad_note", 36)
                            item_uri = params.get("item_uri", "")
                            result = self._load_sample_to_drum_pad(track_index, pad_note, item_uri)
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
                        # ── Arrangement view commands ──────────────────────────────
                        elif command_type == "switch_to_arrangement_view":
                            result = self._switch_to_arrangement_view()
                        elif command_type == "set_current_song_time":
                            time_val = params.get("time", 0.0)
                            result = self._set_current_song_time(time_val)
                        elif command_type == "duplicate_session_clip_to_arrangement":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            destination_time = params.get("destination_time", 0.0)
                            result = self._duplicate_session_clip_to_arrangement(
                                track_index, clip_index, destination_time)
                        # ── Session reorg / mixing (local fork additions) ──
                        elif command_type == "delete_track":
                            result = self._delete_track(params.get("track_index", 0))
                        elif command_type == "create_scene":
                            result = self._create_scene(params.get("index", -1))
                        elif command_type == "set_scene_name":
                            result = self._set_scene_name(
                                params.get("scene_index", 0), params.get("name", ""))
                        elif command_type == "duplicate_clip_to_scene":
                            result = self._duplicate_clip_to_scene(
                                params.get("track_index", 0),
                                params.get("src_clip_index", 0),
                                params.get("dest_clip_index", 0))
                        elif command_type == "set_track_color":
                            result = self._set_track_color(
                                params.get("track_index", 0), params.get("color", 0))
                        elif command_type == "set_track_monitor":
                            result = self._set_track_monitor(
                                params.get("track_index", 0), params.get("state", 1))
                        elif command_type == "set_track_arm":
                            result = self._set_track_arm(
                                params.get("track_index", 0), params.get("armed", True))
                        elif command_type == "set_track_volume":
                            result = self._set_track_volume(
                                params.get("track_index", 0), params.get("value", 0.85))
                        elif command_type == "set_device_parameter":
                            result = self._set_device_parameter(
                                params.get("track_index", 0),
                                params.get("device_index", 0),
                                params.get("parameter", 0),
                                params.get("value", 0.0))
                        elif command_type == "remove_notes_in_range":
                            result = self._remove_notes_in_range(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("from_pitch", 0),
                                params.get("pitch_span", 128),
                                params.get("from_time", 0.0),
                                params.get("time_span", -1.0))
                        elif command_type == "update_notes":
                            result = self._update_notes(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("updates", []))
                        elif command_type == "set_clip_loop":
                            result = self._set_clip_loop(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("properties", {}))
                        elif command_type == "quantize_clip":
                            result = self._quantize_clip(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("grid", 5),
                                params.get("amount", 1.0))
                        elif command_type == "bounce_midi_clip_to_audio":
                            result = self._bounce_midi_clip_to_audio(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("extra_tail_beats", 4.0),
                                params.get("dest_track_index", -1))
                        # ── Feedback-loop tools ──────────────────────────────
                        elif command_type == "undo":
                            result = self._undo()
                        elif command_type == "redo":
                            result = self._redo()
                        elif command_type == "set_track_pan":
                            result = self._set_track_pan(
                                params.get("track_index", 0),
                                params.get("pan", 0.0))
                        elif command_type == "set_track_mute":
                            result = self._set_track_mute(
                                params.get("track_index", 0),
                                params.get("mute", True))
                        elif command_type == "set_track_solo":
                            result = self._set_track_solo(
                                params.get("track_index", 0),
                                params.get("solo", True))
                        elif command_type == "set_send_level":
                            result = self._set_send_level(
                                params.get("track_index", 0),
                                params.get("send_index", 0),
                                params.get("level", 0.0))
                        elif command_type == "create_audio_track":
                            index = params.get("index", -1)
                            result = self._create_audio_track(index)
                        elif command_type == "create_return_track":
                            result = self._create_return_track()

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
                
                # Wait for the response with a timeout. Some commands (notably
                # create_audio_clip, which decodes/imports the audio file on
                # the main thread) can take longer than the default 10s on
                # larger files — give them more headroom.
                long_running_commands = {"create_audio_clip": 60.0}
                queue_timeout = long_running_commands.get(command_type, 10.0)
                try:
                    task_response = response_queue.get(timeout=queue_timeout)
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
            # Read-only arrangement command – no main-thread scheduling required
            elif command_type == "get_arrangement_clips":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_arrangement_clips(track_index)
            # Read-only device introspection – no main-thread scheduling required
            elif command_type == "get_device_parameters":
                response["result"] = self._get_device_parameters(
                    params.get("track_index", 0), params.get("device_index", 0))
            # Read-only MIDI note read – lets the model see a clip's actual notes/chords
            elif command_type == "get_clip_notes":
                response["result"] = self._get_clip_notes(
                    params.get("track_index", 0), params.get("clip_index", 0))
            # Read-only drum rack pad mapping – see which pitch is which instrument
            elif command_type == "get_drum_pad_names":
                response["result"] = self._get_drum_pad_names(
                    params.get("track_index", 0))
            # Read-only scene list
            elif command_type == "get_scene_names":
                response["result"] = self._get_scene_names()
            # Read-only return-track listing
            elif command_type == "get_return_tracks":
                response["result"] = self._get_return_tracks()
            # Read-only meter snapshot
            elif command_type == "get_meters":
                response["result"] = self._get_meters()
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
    
    def _safe_song_property(self, attr, cast, default):
        """Read self._song.<attr> with cast, returning default on common failures.
        Catches only narrow exceptions so genuine bugs still surface."""
        try:
            return cast(getattr(self._song, attr))
        except (AttributeError, TypeError, ValueError):
            return default

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
                },
                # Transport / playback state — lets clients render a live
                # playhead without polling separately. Each property is read
                # via _safe_song_property so an attribute missing on a given
                # Live version falls back to its default rather than breaking
                # the response shape.
                "is_playing":        self._safe_song_property("is_playing",        bool,  False),
                "current_song_time": self._safe_song_property("current_song_time", float, 0.0),
                "song_length":       self._safe_song_property("song_length",       float, 0.0),
                "loop":              self._safe_song_property("loop",              bool,  False),
                "loop_start":        self._safe_song_property("loop_start",        float, 0.0),
                "loop_length":       self._safe_song_property("loop_length",       float, 0.0),
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
            self._song.create_audio_track(index)

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

    def _create_return_track(self):
        """Create a new return track"""
        try:
            self._song.create_return_track()

            new_return_index = len(self._song.return_tracks) - 1
            new_return = self._song.return_tracks[new_return_index]

            result = {
                "index": new_return_index,
                "name": new_return.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating return track: " + str(e))
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

    def _create_audio_clip(self, track_index, clip_index, path):
        """Create an audio clip in the specified audio track clip slot by importing a file.

        Requires Ableton Live 12.0.5 or newer (the underlying
        ClipSlot.create_audio_clip Live API was introduced in 12.0.5 — it is
        not available in earlier 12.0.x releases).
        """
        try:
            if not path:
                raise ValueError("Audio file path is required")

            if not os.path.isabs(path):
                raise ValueError("Audio file path must be absolute (got: %s)" % path)

            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            # Must be an audio track. Audio tracks expose audio input; MIDI
            # tracks don't. Reject MIDI / return tracks up front so the caller
            # gets a clear error instead of a Live API exception.
            if getattr(track, "has_midi_input", False) or not getattr(track, "has_audio_input", True):
                raise ValueError("Track %d is not an audio track" % track_index)

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")

            if not hasattr(clip_slot, "create_audio_clip"):
                raise Exception(
                    "ClipSlot.create_audio_clip is unavailable in this Ableton Live "
                    "version. Requires Live 12.0.5 or newer."
                )

            clip_slot.create_audio_clip(path)

            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length,
                "is_audio_clip": clip_slot.clip.is_audio_clip
            }
            return result
        except Exception as e:
            self.log_message("Error creating audio clip: " + str(e))
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

    def _delete_clip(self, track_index, clip_index):
        """Delete the clip in the specified track/clip slot."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip_slot.delete_clip()
            return {"deleted": True, "track_index": track_index, "clip_index": clip_index}
        except Exception as e:
            self.log_message("Error deleting clip: " + str(e))
            raise

    def _clear_clip_notes(self, track_index, clip_index):
        """Remove all MIDI notes from a clip (keeps the clip itself)."""
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
            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")
            # remove_notes_extended(from_pitch, pitch_span, from_time, time_span)
            try:
                clip.remove_notes_extended(0, 128, 0.0, clip.length)
            except Exception:
                # Fallback for older Live APIs
                clip.select_all_notes()
                clip.replace_selected_notes(tuple())
            return {"cleared": True, "track_index": track_index, "clip_index": clip_index}
        except Exception as e:
            self.log_message("Error clearing clip notes: " + str(e))
            raise

    def _load_sample_to_drum_pad(self, track_index, pad_note, item_uri):
        """Load a browser sample (by URI) onto a specific drum pad of a Drum Rack
        already present on the track. pad_note is the MIDI note of the pad (e.g. 36=C1)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if pad_note < 0 or pad_note > 127:
                raise ValueError("pad_note must be 0-127")

            # Find the Drum Rack device on the track
            drum_rack = None
            for dev in track.devices:
                if getattr(dev, "can_have_drum_pads", False):
                    drum_rack = dev
                    break
            if drum_rack is None:
                raise Exception(
                    "No Drum Rack on track %d. Load a Drum Rack first "
                    "(load_instrument_or_effect with the Drum Rack URI)." % track_index)

            app = self.application()
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))

            # Select track, the drum rack device, and the target pad so the
            # browser loads the sample into THAT pad.
            self._song.view.selected_track = track
            try:
                track.view.selected_device = drum_rack
            except Exception:
                pass
            pad = drum_rack.drum_pads[pad_note]
            try:
                drum_rack.view.selected_drum_pad = pad
            except Exception:
                pass

            app.browser.load_item(item)

            return {
                "loaded": True,
                "track_index": track_index,
                "pad_note": pad_note,
                "pad_name": getattr(pad, "name", ""),
                "item_name": item.name,
            }
        except Exception as e:
            self.log_message("Error loading sample to drum pad: " + str(e))
            self.log_message(traceback.format_exc())
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
    
    # ── Arrangement view implementations ──────────────────────────────────────

    def _switch_to_arrangement_view(self):
        """Switch Ableton's main window to the Arrangement view"""
        try:
            self.application().view.show_view("Arranger")
            return {"view": "Arranger"}
        except Exception as e:
            self.log_message("Error switching to arrangement view: " + str(e))
            raise

    def _set_current_song_time(self, time_val):
        """Move the arrangement playhead to a position in beats"""
        try:
            self._song.current_song_time = float(time_val)
            return {"current_song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error setting current song time: " + str(e))
            raise

    def _get_arrangement_clips(self, track_index):
        """Return all clips placed in the Arrangement timeline for a track.

        Each clip dict contains:
          name, start_time, end_time, length, color,
          is_midi_clip, is_audio_clip, is_playing
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            clips = []

            # track.arrangement_clips is available in Live 11 / 12
            for clip in track.arrangement_clips:
                clips.append({
                    "name": clip.name,
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "length": clip.length,
                    "color": clip.color,
                    "is_midi_clip": clip.is_midi_clip,
                    "is_audio_clip": clip.is_audio_clip,
                    "is_playing": clip.is_playing
                })

            return {
                "track_index": track_index,
                "track_name": track.name,
                "clip_count": len(clips),
                "clips": clips
            }
        except Exception as e:
            self.log_message("Error getting arrangement clips: " + str(e))
            raise

    def _duplicate_session_clip_to_arrangement(self, track_index, clip_index, destination_time):
        """Copy a Session-view clip into the Arrangement timeline.

        Uses the real Live API:
          track.duplicate_clip_to_arrangement(clip, destination_time)

        Available in Live 11 / 12.  destination_time is in beats from the
        start of the arrangement.
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip slot index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception(
                    "No clip in slot " + str(clip_index) +
                    " on track " + str(track_index)
                )

            clip = clip_slot.clip

            # Duplicate to arrangement at the requested beat position
            track.duplicate_clip_to_arrangement(clip, float(destination_time))

            return {
                "success": True,
                "track_index": track_index,
                "track_name": track.name,
                "clip_name": clip.name,
                "destination_time": destination_time
            }
        except Exception as e:
            self.log_message("Error duplicating clip to arrangement: " + str(e))
            raise

    # ── Browser implementations ───────────────────────────────────────────────

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
                if path_parts[0].lower() == "instruments":
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
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
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
    
    # Substring markers that point a URI at a likely root. If no marker
    # matches we fall back to the default order, so this is purely an
    # optimisation — never a correctness change.
    _URI_ROOT_HINTS = (
        ('plugins',       ('vst:', 'vst3:', 'au:', 'query:plugins', 'plugin#')),
        ('max_for_live',  ('max for live', 'maxforlive', 'm4l', 'query:max')),
        ('user_library',  ('user library', 'userlibrary', 'query:user library', 'query:user-library')),
        ('packs',         ('query:packs', '/packs/')),
        ('samples',       ('query:samples', 'sample:', '/samples/')),
        ('drums',         ('query:drums', '/drums/')),
        ('instruments',   ('query:instruments', '/instruments/')),
        ('sounds',        ('query:sounds', '/sounds/')),
        ('audio_effects', ('query:audio effects', 'audioeffects', '/audio_effects/')),
        ('midi_effects',  ('query:midi effects', 'midieffects', '/midi_effects/')),
    )

    def _order_roots_by_uri(self, roots, uri):
        """Reorder ``roots`` so the URI's likely root is walked first."""
        if not isinstance(uri, (bytes, str)) or not uri:
            return roots
        lowered = uri.lower()
        for attr, markers in self._URI_ROOT_HINTS:
            if any(m in lowered for m in markers):
                head = [(a, r) for (a, r) in roots if a == attr]
                tail = [(a, r) for (a, r) in roots if a != attr]
                return head + tail
        return roots

    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI.

        Top-level lookups are memoised on ``self._uri_cache`` so repeated
        loads of the same URI don't re-walk the entire browser tree.
        """
        if current_depth == 0:
            cache = getattr(self, '_uri_cache', None)
            if cache is None:
                self._uri_cache = cache = {}
            if uri in cache:
                return cache[uri]
            result = self._walk_browser_for_uri(browser_or_item, uri, max_depth, 0)
            if result is not None:
                cache[uri] = result
            return result
        return self._walk_browser_for_uri(browser_or_item, uri, max_depth, current_depth)

    def _walk_browser_for_uri(self, browser_or_item, uri, max_depth, current_depth):
        """Recursive walk used by :py:meth:`_find_browser_item_by_uri`."""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item

            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None

            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                roots = [
                    ('instruments', browser_or_item.instruments),
                    ('sounds', browser_or_item.sounds),
                    ('drums', browser_or_item.drums),
                    ('audio_effects', browser_or_item.audio_effects),
                    ('midi_effects', browser_or_item.midi_effects),
                ]
                for extra_attr in ('plugins', 'max_for_live', 'user_library', 'packs', 'samples'):
                    if hasattr(browser_or_item, extra_attr):
                        try:
                            roots.append((extra_attr, getattr(browser_or_item, extra_attr)))
                        except (AttributeError, RuntimeError) as e:
                            self.log_message("Could not access browser.{0}: {1}".format(extra_attr, str(e)))

                for _attr, category in self._order_roots_by_uri(roots, uri):
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

    # ── Session reorg / mixing helpers (local fork additions) ──────────────

    def _delete_track(self, track_index):
        """Delete a track by index."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            name = self._song.tracks[track_index].name
            self._song.delete_track(track_index)
            return {"deleted": True, "track_index": track_index, "name": name}
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _create_scene(self, index):
        """Create a new scene at index (-1 = end of list)."""
        try:
            self._song.create_scene(index)
            scene_index = len(self._song.scenes) - 1 if index == -1 else index
            return {"index": scene_index, "name": self._song.scenes[scene_index].name}
        except Exception as e:
            self.log_message("Error creating scene: " + str(e))
            raise

    def _set_scene_name(self, scene_index, name):
        """Set the name of a scene."""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            self._song.scenes[scene_index].name = name
            return {"index": scene_index, "name": name}
        except Exception as e:
            self.log_message("Error setting scene name: " + str(e))
            raise

    def _duplicate_clip_to_scene(self, track_index, src_clip_index, dest_clip_index):
        """Copy a clip (MIDI or audio) from one slot to another slot on the same track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            slots = self._song.tracks[track_index].clip_slots
            if src_clip_index < 0 or src_clip_index >= len(slots):
                raise IndexError("Source clip index out of range")
            if dest_clip_index < 0 or dest_clip_index >= len(slots):
                raise IndexError("Destination clip index out of range")
            src = slots[src_clip_index]
            dst = slots[dest_clip_index]
            if not src.has_clip:
                raise Exception("No clip in source slot")
            if dst.has_clip:
                raise Exception("Destination slot already has a clip")
            if not hasattr(src, "duplicate_clip_to"):
                raise Exception("ClipSlot.duplicate_clip_to unavailable (needs Live 11+)")
            src.duplicate_clip_to(dst)
            return {"track_index": track_index, "from": src_clip_index,
                    "to": dest_clip_index,
                    "name": dst.clip.name if dst.has_clip else None}
        except Exception as e:
            self.log_message("Error duplicating clip to scene: " + str(e))
            raise

    def _set_track_color(self, track_index, color):
        """Set a track's color. Accepts int 0xRRGGBB or a [r, g, b] list."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if isinstance(color, (list, tuple)) and len(color) == 3:
                r, g, b = [max(0, min(255, int(c))) for c in color]
                value = (r << 16) | (g << 8) | b
            else:
                value = int(color)
            track.color = value
            return {"track_index": track_index, "color": track.color}
        except Exception as e:
            self.log_message("Error setting track color: " + str(e))
            raise

    def _set_track_monitor(self, track_index, state):
        """Set monitoring state: 0/In, 1/Auto, 2/Off (int or string)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            mapping = {"in": 0, "auto": 1, "off": 2}
            if isinstance(state, str):
                val = mapping.get(state.strip().lower())
                if val is None:
                    raise ValueError("monitor state must be in/auto/off or 0/1/2")
            else:
                val = int(state)
            track.current_monitoring_state = val
            return {"track_index": track_index,
                    "current_monitoring_state": track.current_monitoring_state}
        except Exception as e:
            self.log_message("Error setting track monitor: " + str(e))
            raise

    def _set_track_arm(self, track_index, armed):
        """Arm / disarm a track for recording and input monitoring."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if not getattr(track, "can_be_armed", False):
                raise Exception("Track cannot be armed")
            track.arm = bool(armed)
            return {"track_index": track_index, "arm": track.arm}
        except Exception as e:
            self.log_message("Error setting track arm: " + str(e))
            raise

    def _set_track_volume(self, track_index, value):
        """Set a track's mixer volume (normalized 0.0-1.0 fader; 0.85 ~ 0 dB)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            vol = self._song.tracks[track_index].mixer_device.volume
            v = max(vol.min, min(vol.max, float(value)))
            vol.value = v
            return {"track_index": track_index, "volume": vol.value}
        except Exception as e:
            self.log_message("Error setting track volume: " + str(e))
            raise

    def _get_device_parameters(self, track_index, device_index):
        """List a device's parameters (index, name, value, min, max)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            params = []
            for i, p in enumerate(device.parameters):
                params.append({
                    "index": i,
                    "name": p.name,
                    "value": p.value,
                    "min": p.min,
                    "max": p.max,
                })
            return {"track_index": track_index, "device_index": device_index,
                    "device_name": device.name, "parameters": params}
        except Exception as e:
            self.log_message("Error getting device parameters: " + str(e))
            raise

    def _set_device_parameter(self, track_index, device_index, parameter, value):
        """Set a device parameter by index (int) or name (str) to value."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            param = None
            if isinstance(parameter, bool):
                raise ValueError("parameter must be an index or a name")
            if isinstance(parameter, int):
                if parameter < 0 or parameter >= len(device.parameters):
                    raise IndexError("Parameter index out of range")
                param = device.parameters[parameter]
            else:
                target = str(parameter).strip().lower()
                for p in device.parameters:
                    if p.name.strip().lower() == target:
                        param = p
                        break
                if param is None:
                    raise Exception("Parameter '%s' not found" % parameter)
            v = max(param.min, min(param.max, float(value)))
            param.value = v
            return {"track_index": track_index, "device_index": device_index,
                    "parameter": param.name, "value": param.value,
                    "min": param.min, "max": param.max}
        except Exception as e:
            self.log_message("Error setting device parameter: " + str(e))
            raise

    def _get_clip_notes(self, track_index, clip_index):
        """Read the MIDI notes of a clip (pitch/start/duration/velocity/mute)."""
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
            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")
            length = clip.length
            notes = []
            try:
                # Live 11+ preferred API: list of MidiNote objects
                extended = clip.get_notes_extended(0, 128, 0.0, length)
                for n in extended:
                    notes.append({
                        "pitch": int(n.pitch),
                        "start_time": float(n.start_time),
                        "duration": float(n.duration),
                        "velocity": float(n.velocity),
                        "mute": bool(n.mute),
                    })
            except (AttributeError, RuntimeError, TypeError):
                # Fallback: legacy get_notes -> tuples (pitch, time, dur, vel, mute)
                raw = clip.get_notes(0.0, 0, length, 128)
                for tup in raw:
                    notes.append({
                        "pitch": int(tup[0]),
                        "start_time": float(tup[1]),
                        "duration": float(tup[2]),
                        "velocity": float(tup[3]),
                        "mute": bool(tup[4]),
                    })
            notes.sort(key=lambda x: (x["start_time"], x["pitch"]))
            return {"track_index": track_index, "clip_index": clip_index,
                    "name": clip.name, "length": length,
                    "note_count": len(notes), "notes": notes}
        except Exception as e:
            self.log_message("Error getting clip notes: " + str(e))
            raise

    def _get_midi_clip(self, track_index, clip_index):
        """Shared guard: return the MIDI clip at track/slot or raise."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        clip_slot = track.clip_slots[clip_index]
        if not clip_slot.has_clip:
            raise Exception("No clip in slot")
        clip = clip_slot.clip
        if not clip.is_midi_clip:
            raise Exception("Clip is not a MIDI clip")
        return clip

    def _remove_notes_in_range(self, track_index, clip_index, from_pitch,
                               pitch_span, from_time, time_span):
        """Surgically remove notes in a pitch/time window (keeps the rest)."""
        try:
            clip = self._get_midi_clip(track_index, clip_index)
            if time_span < 0:
                time_span = clip.length - from_time
            clip.remove_notes_extended(int(from_pitch), int(pitch_span),
                                       float(from_time), float(time_span))
            return {"removed": True, "from_pitch": from_pitch,
                    "pitch_span": pitch_span, "from_time": from_time,
                    "time_span": time_span}
        except Exception as e:
            self.log_message("Error removing notes in range: " + str(e))
            raise

    def _update_notes(self, track_index, clip_index, updates):
        """Surgically modify existing notes without rewriting the clip.
        Each update matches notes by pitch + start_time (within tolerance)
        and applies new velocity/duration/start_time/mute via
        apply_note_modifications (Live 11+)."""
        try:
            clip = self._get_midi_clip(track_index, clip_index)
            all_notes = clip.get_notes_extended(0, 128, 0.0, clip.length)
            modified = []
            not_found = []
            for upd in updates:
                pitch = int(upd.get("pitch", -1))
                start = float(upd.get("start_time", -1.0))
                tol = float(upd.get("tolerance", 0.05))
                hit = False
                for n in all_notes:
                    if int(n.pitch) == pitch and abs(float(n.start_time) - start) <= tol:
                        if "new_velocity" in upd:
                            n.velocity = float(upd["new_velocity"])
                        if "new_duration" in upd:
                            n.duration = float(upd["new_duration"])
                        if "new_start_time" in upd:
                            n.start_time = float(upd["new_start_time"])
                        if "new_mute" in upd:
                            n.mute = bool(upd["new_mute"])
                        if "new_pitch" in upd:
                            n.pitch = int(upd["new_pitch"])
                        modified.append({"pitch": pitch, "start_time": start})
                        hit = True
                if not hit:
                    not_found.append({"pitch": pitch, "start_time": start})
            if modified:
                clip.apply_note_modifications(all_notes)
            return {"modified_count": len(modified), "modified": modified,
                    "not_found": not_found}
        except Exception as e:
            self.log_message("Error updating notes: " + str(e))
            raise

    def _set_clip_loop(self, track_index, clip_index, properties):
        """Set clip loop/marker properties: looping, loop_start, loop_end,
        start_marker, end_marker (beats)."""
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
            applied = {}
            # Order matters: enable looping before moving loop points,
            # and set end before start when shrinking (Live validates ranges).
            if "looping" in properties:
                clip.looping = bool(properties["looping"])
                applied["looping"] = clip.looping
            for key in ("loop_end", "loop_start", "end_marker", "start_marker"):
                if key in properties:
                    setattr(clip, key, float(properties[key]))
                    applied[key] = float(getattr(clip, key))
            return {"track_index": track_index, "clip_index": clip_index,
                    "applied": applied}
        except Exception as e:
            self.log_message("Error setting clip loop: " + str(e))
            raise

    def _quantize_clip(self, track_index, clip_index, grid, amount):
        """Quantize a MIDI clip. grid: RecordingQuantization enum int
        (1=1/4, 2=1/8, 3=1/8T, 4=1/8+T, 5=1/16, 6=1/16T, 7=1/16+T, 8=1/32).
        amount: 0.0-1.0 (1.0 = hard snap, 0.5 = half-way = keeps groove)."""
        try:
            clip = self._get_midi_clip(track_index, clip_index)
            clip.quantize(int(grid), float(amount))
            return {"quantized": True, "grid": grid, "amount": amount}
        except Exception as e:
            self.log_message("Error quantizing clip: " + str(e))
            raise

    def _get_drum_pad_names(self, track_index):
        """Map drum pad MIDI notes to their pad/instrument names for the
        first Drum Rack found on the track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            for device in track.devices:
                if getattr(device, "can_have_drum_pads", False):
                    pads = []
                    for pad in device.drum_pads:
                        if pad.chains:  # only pads with something loaded
                            pads.append({
                                "note": int(pad.note),
                                "name": str(pad.name),
                            })
                    pads.sort(key=lambda p: p["note"])
                    return {"track_index": track_index,
                            "device_name": str(device.name),
                            "pad_count": len(pads), "pads": pads}
            raise Exception("No Drum Rack found on track")
        except Exception as e:
            self.log_message("Error getting drum pad names: " + str(e))
            raise

    def _bounce_midi_clip_to_audio(self, track_index, clip_index,
                                   extra_tail_beats, dest_track_index):
        """Record a MIDI track's clip output onto an audio track in real time
        (resampling-record path — freeze/flatten is not exposed in the LOM).
        Fires the source clip, records into the same scene row on the audio
        track, and self-schedules the stop after clip length + tail. Returns
        immediately; poll get_track_info to see the finished audio clip."""
        try:
            song = self._song
            if track_index < 0 or track_index >= len(song.tracks):
                raise IndexError("Source track index out of range")
            source_track = song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(source_track.clip_slots):
                raise IndexError("Clip index out of range")
            source_slot = source_track.clip_slots[clip_index]
            if not source_slot.has_clip:
                raise Exception("No clip in source slot")
            clip_length = float(source_slot.clip.length)
            tempo = float(song.tempo)

            # Destination audio track: reuse given index or create at end
            if dest_track_index >= 0:
                if dest_track_index >= len(song.tracks):
                    raise IndexError("Destination track index out of range")
                audio_track = song.tracks[dest_track_index]
                if audio_track.has_midi_input:
                    raise Exception("Destination track is not an audio track")
                dest_idx = dest_track_index
            else:
                song.create_audio_track(-1)
                dest_idx = len(song.tracks) - 1
                audio_track = song.tracks[dest_idx]
                audio_track.name = str(source_track.name) + " [BOUNCE]"

            if audio_track.clip_slots[clip_index].has_clip:
                raise Exception("Destination slot %d on track %d already has "
                                "a clip — clear it first" % (clip_index, dest_idx))

            # Input routing: find the source track among available inputs
            source_name = str(source_track.name)
            routing_match = None
            for rt in audio_track.available_input_routing_types:
                if source_name in str(rt.display_name):
                    routing_match = rt
                    break
            if routing_match is None:
                raise Exception("Could not find input routing for track '%s'. "
                                "Available: %s" % (source_name,
                                [str(rt.display_name) for rt in
                                 audio_track.available_input_routing_types][:20]))
            audio_track.input_routing_type = routing_match
            # Channel: prefer Post FX tap
            for ch in audio_track.available_input_routing_channels:
                if "Post FX" in str(ch.display_name):
                    audio_track.input_routing_channel = ch
                    break

            audio_track.current_monitoring_state = 2  # Off — avoid doubling
            audio_track.arm = True

            prev_quant = song.clip_trigger_quantization
            song.clip_trigger_quantization = 0  # start immediately
            song.session_record = True
            source_slot.fire()
            audio_track.clip_slots[clip_index].fire()

            duration_s = (clip_length + float(extra_tail_beats)) * 60.0 / tempo

            def stop_bounce():
                try:
                    song.session_record = False
                    audio_track.clip_slots[clip_index].stop()
                    source_slot.stop()
                    audio_track.arm = False
                    song.clip_trigger_quantization = prev_quant
                    slot = audio_track.clip_slots[clip_index]
                    if slot.has_clip:
                        new_clip = slot.clip
                        try:
                            new_clip.name = str(source_slot.clip.name) + " [audio]"
                            if new_clip.looping:
                                new_clip.loop_end = clip_length
                        except Exception as e2:
                            self.log_message("Bounce post-trim skipped: " + str(e2))
                    self.log_message("Bounce finished on track %d slot %d"
                                     % (dest_idx, clip_index))
                except Exception as e1:
                    self.log_message("Error stopping bounce: " + str(e1))

            # schedule_message ticks are ~100ms; +10 ticks safety margin
            self.schedule_message(int(duration_s * 10) + 10, stop_bounce)

            return {"recording": True, "dest_track_index": dest_idx,
                    "clip_index": clip_index,
                    "duration_seconds": round(duration_s + 1.0, 1),
                    "note": "Recording in real time; auto-stops. Check "
                            "get_track_info(track_index=%d) after ~%ds."
                            % (dest_idx, int(duration_s + 2))}
        except Exception as e:
            self.log_message("Error bouncing MIDI clip to audio: " + str(e))
            raise

    def _get_scene_names(self):
        """List all scenes with index, name, tempo/time-sig hints Live parsed
        from the name, and whether the scene is empty."""
        try:
            scenes = []
            for i, scene in enumerate(self._song.scenes):
                entry = {"index": i, "name": str(scene.name)}
                try:
                    entry["is_empty"] = bool(scene.is_empty)
                except Exception:
                    pass
                try:
                    if scene.tempo > 0:
                        entry["tempo"] = float(scene.tempo)
                except Exception:
                    pass
                scenes.append(entry)
            return {"scene_count": len(scenes), "scenes": scenes}
        except Exception as e:
            self.log_message("Error getting scene names: " + str(e))
            raise

    # ── Feedback-loop tool implementations ──────────────────────────────────

    def _undo(self):
        """Undo the last action and report can_undo/can_redo."""
        try:
            self._song.undo()
            return {
                "can_undo": bool(self._song.can_undo),
                "can_redo": bool(self._song.can_redo),
            }
        except Exception as e:
            self.log_message("Error performing undo: " + str(e))
            raise

    def _redo(self):
        """Redo the last undone action and report can_undo/can_redo."""
        try:
            self._song.redo()
            return {
                "can_undo": bool(self._song.can_undo),
                "can_redo": bool(self._song.can_redo),
            }
        except Exception as e:
            self.log_message("Error performing redo: " + str(e))
            raise

    def _set_track_pan(self, track_index, pan):
        """Set a track's stereo pan (-1.0 left … 0.0 center … 1.0 right)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            panning = self._song.tracks[track_index].mixer_device.panning
            v = max(panning.min, min(panning.max, float(pan)))
            panning.value = v
            return {"track_index": track_index, "pan": panning.value}
        except Exception as e:
            self.log_message("Error setting track pan: " + str(e))
            raise

    def _set_track_mute(self, track_index, mute):
        """Mute or unmute a track (track.mute = True means muted)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            self._song.tracks[track_index].mute = bool(mute)
            return {"track_index": track_index,
                    "mute": bool(self._song.tracks[track_index].mute)}
        except Exception as e:
            self.log_message("Error setting track mute: " + str(e))
            raise

    def _set_track_solo(self, track_index, solo):
        """Solo or unsolo a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            self._song.tracks[track_index].solo = bool(solo)
            return {"track_index": track_index,
                    "solo": bool(self._song.tracks[track_index].solo)}
        except Exception as e:
            self.log_message("Error setting track solo: " + str(e))
            raise

    def _get_return_tracks(self):
        """List return tracks with names, volume, pan, and device names."""
        try:
            returns = []
            for i, rt in enumerate(self._song.return_tracks):
                entry = {
                    "index": i,
                    "name": str(rt.name),
                    "volume": rt.mixer_device.volume.value,
                    "pan": rt.mixer_device.panning.value,
                    "devices": [str(d.name) for d in rt.devices],
                }
                returns.append(entry)
            return {"return_track_count": len(returns), "return_tracks": returns}
        except Exception as e:
            self.log_message("Error getting return tracks: " + str(e))
            raise

    def _set_send_level(self, track_index, send_index, level):
        """Set a track's send level to a return track (normalized 0.0-1.0)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            sends = track.mixer_device.sends
            if send_index < 0 or send_index >= len(sends):
                raise IndexError("Send index out of range (track has %d sends)" % len(sends))
            send = sends[send_index]
            v = max(send.min, min(send.max, float(level)))
            send.value = v
            return {"track_index": track_index, "send_index": send_index,
                    "level": send.value}
        except Exception as e:
            self.log_message("Error setting send level: " + str(e))
            raise

    def _get_meters(self):
        """Snapshot output meter levels for all tracks + master (single call)."""
        try:
            tracks_data = []
            for i, track in enumerate(self._song.tracks):
                entry = {"index": i, "name": str(track.name)}
                try:
                    entry["output_meter_left"] = float(track.output_meter_left)
                except Exception:
                    pass
                try:
                    entry["output_meter_right"] = float(track.output_meter_right)
                except Exception:
                    pass
                try:
                    entry["output_meter_level"] = float(track.output_meter_level)
                except Exception:
                    pass
                tracks_data.append(entry)
            # Return tracks
            return_data = []
            for i, rt in enumerate(self._song.return_tracks):
                entry = {"index": i, "name": str(rt.name)}
                try:
                    entry["output_meter_left"] = float(rt.output_meter_left)
                except Exception:
                    pass
                try:
                    entry["output_meter_right"] = float(rt.output_meter_right)
                except Exception:
                    pass
                try:
                    entry["output_meter_level"] = float(rt.output_meter_level)
                except Exception:
                    pass
                return_data.append(entry)
            # Master
            master_entry = {"name": "Master"}
            mt = self._song.master_track
            try:
                master_entry["output_meter_left"] = float(mt.output_meter_left)
            except Exception:
                pass
            try:
                master_entry["output_meter_right"] = float(mt.output_meter_right)
            except Exception:
                pass
            try:
                master_entry["output_meter_level"] = float(mt.output_meter_level)
            except Exception:
                pass
            return {
                "tracks": tracks_data,
                "return_tracks": return_data,
                "master": master_entry,
            }
        except Exception as e:
            self.log_message("Error getting meters: " + str(e))
            raise
