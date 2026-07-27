# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
import os
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union, Optional

ABLETON_HOST = os.environ.get("ABLETON_HOST", "127.0.0.1")
ABLETON_PORT = int(os.environ.get("ABLETON_PORT", "9877"))

MAX_RESPONSE_BYTES = 4 * 1024 * 1024

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
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton at {self.host}:{self.port}: {str(e)}")
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

    def receive_full_response(
        self,
        sock,
        buffer_size=8192,
        timeout=15.0,
        max_response_bytes=MAX_RESPONSE_BYTES,
    ):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        received_bytes = 0
        sock.settimeout(timeout)
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    received_bytes += len(chunk)
                    if received_bytes > max_response_bytes:
                        raise ValueError(
                            f"Ableton response exceeded {max_response_bytes} bytes"
                        )
                    
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
            "create_midi_track", "create_audio_track", "create_return_track", "set_track_name",
            "create_clip", "create_audio_clip", "add_notes_to_clip", "set_clip_name",
            "delete_clip", "clear_clip_notes", "load_sample_to_drum_pad",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "start_playback", "stop_playback", "load_instrument_or_effect",
            "delete_track", "create_scene", "set_scene_name",
            "duplicate_clip_to_scene", "set_track_color", "set_track_monitor",
            "set_track_arm", "set_track_volume", "set_device_parameter",
            "remove_notes_in_range", "update_notes", "set_clip_loop",
            "quantize_clip", "bounce_midi_clip_to_audio", "undo", "redo",
            "set_track_pan", "set_track_mute", "set_track_solo",
            "set_send_level",
            # Arrangement view commands
            "switch_to_arrangement_view", "set_current_song_time",
            "duplicate_session_clip_to_arrangement"
        ]

        # Commands whose work on Live's main thread can take noticeably longer
        # than the default modifying-command budget (e.g. importing/decoding a
        # large audio file). Give them a wider socket timeout so we don't time
        # out before the Remote Script's own queue does.
        long_running_commands = {"create_audio_clip": 65.0}
        
        try:
            logger.info("Sending command: %s", command_type)
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # Set timeout based on command type
            if command_type in long_running_commands:
                timeout = long_running_commands[command_type]
            else:
                timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)

            # Receive the response
            response_data = self.receive_full_response(self.sock, timeout=timeout)
            logger.info(f"Received {len(response_data)} bytes of data")

            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")

            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
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
    "AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection

    if _ableton_connection is not None and _ableton_connection.sock is not None:
        try:
            # Check if the socket is still alive by peeking for data
            # MSG_PEEK + MSG_DONTWAIT will raise BlockingIOError if alive but no data,
            # or return b'' if the remote end has closed the connection.
            _ableton_connection.sock.setblocking(False)
            try:
                data = _ableton_connection.sock.recv(1, socket.MSG_PEEK)
                if data == b'':
                    raise ConnectionError("Remote end closed")
            except BlockingIOError:
                pass  # Socket is alive, just no data waiting — this is normal
            finally:
                _ableton_connection.sock.setblocking(True)
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
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton at {ABLETON_HOST}:{ABLETON_PORT} (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host=ABLETON_HOST, port=ABLETON_PORT)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    return _ableton_connection
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None

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
    """Get detailed information about the current Ableton session

    Parameters:
    """
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
    - index: The index to insert the track at (-1 = append at end)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": index})
        return f"Created new audio track at index {result.get('index', '?')}: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"


@mcp.tool()
def create_return_track(ctx: Context) -> str:
    """
    Create a new return (send/FX) track in the Ableton session.

    Return tracks are appended at the end of the return track list.

    Parameters:
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_return_track", {})
        return f"Created new return track at index {result.get('index', '?')}: {result.get('name', 'unknown')}"
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
def create_audio_clip(ctx: Context, track_index: int, clip_index: int, path: str) -> str:
    """
    Create a new audio clip in an audio track's clip slot by importing a file.

    Requires Ableton Live 12.0.5 or newer — the underlying
    ClipSlot.create_audio_clip Live API was introduced in 12.0.5 and is not
    available in earlier 12.0.x releases.

    Parameters:
    - track_index: The index of the audio track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - path: Absolute path to a supported audio file (e.g. a .wav). The target
      track must be an audio track and the clip slot must be empty.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "path": path
        })
        return f"Created audio clip '{result.get('name', 'clip')}' at track {track_index}, slot {clip_index} (length {result.get('length', '?')} beats)"
    except Exception as e:
        logger.error(f"Error creating audio clip: {str(e)}")
        return f"Error creating audio clip: {str(e)}"

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
def delete_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete the clip in the specified track/clip slot (empties the slot).

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot to empty
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Deleted clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error deleting clip: {str(e)}")
        return f"Error deleting clip: {str(e)}"

@mcp.tool()
def clear_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Remove ALL MIDI notes from a clip while keeping the clip itself (so you can
    rewrite it from scratch without deleting/recreating the slot).

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("clear_clip_notes", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Cleared all notes from clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error clearing clip notes: {str(e)}")
        return f"Error clearing clip notes: {str(e)}"

@mcp.tool()
def load_sample_to_drum_pad(ctx: Context, track_index: int, pad_note: int, item_uri: str) -> str:
    """
    Load a browser sample (by its URI) onto a specific pad of a Drum Rack that is
    already on the track. This lets you build a custom drum kit pad-by-pad.

    Prerequisite: a Drum Rack must already be loaded on the track (use
    load_instrument_or_effect with the Drum Rack URI 'query:Drums#Drum%20Rack',
    or any drum kit). Get the sample's URI from get_browser_items_at_path.

    Parameters:
    - track_index: The index of the track holding the Drum Rack
    - pad_note: MIDI note number of the target pad (e.g. 36=C1, 38=D1, 42=F#1)
    - item_uri: Browser URI of the sample to load onto that pad
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_sample_to_drum_pad", {
            "track_index": track_index,
            "pad_note": pad_note,
            "item_uri": item_uri
        })
        return f"Loaded sample onto pad {pad_note} of Drum Rack on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading sample to drum pad: {str(e)}")
        return f"Error loading sample to drum pad: {str(e)}"

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
    """Start playing the Ableton session.

    Parameters:
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session.

    Parameters:
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

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

# ── Arrangement view tools ────────────────────────────────────────────────────

@mcp.tool()
def switch_to_arrangement_view(ctx: Context) -> str:
    """Switch Ableton's main window to the Arrangement view.

    Parameters:
    """
    try:
        ableton = get_ableton_connection()
        ableton.send_command("switch_to_arrangement_view")
        return "Switched to Arrangement view"
    except Exception as e:
        logger.error(f"Error switching to arrangement view: {str(e)}")
        return f"Error switching to arrangement view: {str(e)}"


@mcp.tool()
def set_arrangement_time(ctx: Context, time: float) -> str:
    """
    Move the arrangement playhead to a specific position.

    Parameters:
    - time: Position in beats from the start of the arrangement (e.g. 8.0 = bar 3 in 4/4)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_current_song_time", {"time": time})
        return f"Playhead moved to beat {result.get('current_song_time', time)}"
    except Exception as e:
        logger.error(f"Error setting arrangement time: {str(e)}")
        return f"Error setting arrangement time: {str(e)}"


@mcp.tool()
def get_arrangement_clips(ctx: Context, track_index: int) -> str:
    """
    List all clips placed in the Arrangement timeline for a track.

    Returns each clip's name, start_time, end_time, length, and type.

    Parameters:
    - track_index: The index of the track to inspect
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_clips", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting arrangement clips: {str(e)}")
        return f"Error getting arrangement clips: {str(e)}"


@mcp.tool()
def duplicate_to_arrangement(
    ctx: Context,
    track_index: int,
    clip_index: int,
    destination_time: float
) -> str:
    """
    Copy a Session-view clip into the Arrangement timeline.

    Uses Live's track.duplicate_clip_to_arrangement() API (Live 11 / 12).
    The clip is placed at destination_time beats from the start of the
    arrangement on the same track it lives in.

    Typical workflow:
      1. create_clip / add_notes_to_clip to build a Session clip
      2. Call duplicate_to_arrangement once per bar/section you need
      3. Call switch_to_arrangement_view to confirm the result in Live

    Parameters:
    - track_index:       Index of the track that owns the Session clip
    - clip_index:        Index of the clip slot in that track (Session view)
    - destination_time:  Beat position in the arrangement to place the clip
                         (e.g. 0.0 = start, 8.0 = bar 3 in 4/4)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "duplicate_session_clip_to_arrangement",
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "destination_time": destination_time
            }
        )
        clip_name = result.get("clip_name", "clip")
        track_name = result.get("track_name", f"track {track_index}")
        return (
            f"Duplicated '{clip_name}' from Session slot {clip_index} "
            f"on '{track_name}' to arrangement at beat {destination_time}"
        )
    except Exception as e:
        logger.error(f"Error duplicating clip to arrangement: {str(e)}")
        return f"Error duplicating clip to arrangement: {str(e)}"


# ── Session reorg / mixing tools (local fork additions) ───────────────────

@mcp.tool()
def delete_track(ctx: Context, track_index: int) -> str:
    """
    Delete a track by its index. Indices of later tracks shift down by one.

    Parameters:
    - track_index: The index of the track to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_track", {"track_index": track_index})
        return f"Deleted track {track_index} ('{result.get('name', '?')}')"
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        return f"Error deleting track: {str(e)}"


@mcp.tool()
def create_scene(ctx: Context, index: int = -1) -> str:
    """
    Create a new scene (Session-view row). index=-1 appends at the end.

    Parameters:
    - index: The position to insert the scene at (-1 = end)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {"index": index})
        return f"Created scene at index {result.get('index')}"
    except Exception as e:
        logger.error(f"Error creating scene: {str(e)}")
        return f"Error creating scene: {str(e)}"


@mcp.tool()
def set_scene_name(ctx: Context, scene_index: int, name: str) -> str:
    """
    Set the name of a scene (Session-view row), e.g. 'INTRO', 'HOOK'.

    Parameters:
    - scene_index: The index of the scene
    - name: The new scene name
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_name", {"scene_index": scene_index, "name": name})
        return f"Renamed scene {scene_index} to '{result.get('name', name)}'"
    except Exception as e:
        logger.error(f"Error setting scene name: {str(e)}")
        return f"Error setting scene name: {str(e)}"


@mcp.tool()
def duplicate_clip_to_scene(ctx: Context, track_index: int, src_clip_index: int,
                            dest_clip_index: int) -> str:
    """
    Copy a clip (MIDI or AUDIO) from one slot to another empty slot on the SAME
    track. This is how you place a loop into several scenes for live performance
    — and unlike create_clip it works for audio clips too.

    Parameters:
    - track_index: The track that owns the clip
    - src_clip_index: The slot index to copy FROM (must contain a clip)
    - dest_clip_index: The slot index to copy TO (must be empty)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip_to_scene", {
            "track_index": track_index,
            "src_clip_index": src_clip_index,
            "dest_clip_index": dest_clip_index,
        })
        return (f"Copied clip on track {track_index} from slot {src_clip_index} "
                f"to slot {dest_clip_index}")
    except Exception as e:
        logger.error(f"Error duplicating clip to scene: {str(e)}")
        return f"Error duplicating clip to scene: {str(e)}"


@mcp.tool()
def set_track_color(ctx: Context, track_index: int, color: Union[int, List[int]]) -> str:
    """
    Set a track's color. Pass either an int 0xRRGGBB (e.g. 16711680 for red) or
    a [r, g, b] list with 0-255 values.

    Parameters:
    - track_index: The index of the track
    - color: 0xRRGGBB int, or [r, g, b]
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_color", {"track_index": track_index, "color": color})
        return f"Set track {track_index} color to {result.get('color')}"
    except Exception as e:
        logger.error(f"Error setting track color: {str(e)}")
        return f"Error setting track color: {str(e)}"


@mcp.tool()
def set_track_monitor(ctx: Context, track_index: int, state: Union[int, str]) -> str:
    """
    Set a track's input monitoring. Use 'in'/0 to always hear the live input
    (e.g. a mic), 'auto'/1 for monitor-when-armed, 'off'/2 for none.

    Parameters:
    - track_index: The index of the track
    - state: 'in'|'auto'|'off' or 0|1|2
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_monitor", {"track_index": track_index, "state": state})
        return f"Set track {track_index} monitor to state {result.get('current_monitoring_state')}"
    except Exception as e:
        logger.error(f"Error setting track monitor: {str(e)}")
        return f"Error setting track monitor: {str(e)}"


@mcp.tool()
def set_track_arm(ctx: Context, track_index: int, armed: bool = True) -> str:
    """
    Arm or disarm a track for recording / input monitoring.

    Parameters:
    - track_index: The index of the track
    - armed: True to arm, False to disarm
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_arm", {"track_index": track_index, "armed": armed})
        return f"Set track {track_index} arm to {result.get('arm')}"
    except Exception as e:
        logger.error(f"Error setting track arm: {str(e)}")
        return f"Error setting track arm: {str(e)}"


@mcp.tool()
def set_track_volume(ctx: Context, track_index: int, value: float) -> str:
    """
    Set a track's mixer fader. value is the normalized 0.0-1.0 position where
    ~0.85 is 0 dB and 1.0 is +6 dB (the fader max). For bigger gain than the
    fader allows, add a Utility device and use set_device_parameter on its Gain.

    Parameters:
    - track_index: The index of the track
    - value: Normalized volume 0.0-1.0
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_volume", {"track_index": track_index, "value": value})
        return f"Set track {track_index} volume to {result.get('volume')}"
    except Exception as e:
        logger.error(f"Error setting track volume: {str(e)}")
        return f"Error setting track volume: {str(e)}"


@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    List every parameter of a device (index, name, current value, min, max). Use
    this before set_device_parameter to find the right parameter and its range.

    Parameters:
    - track_index: The track holding the device
    - device_index: The device's index in that track's chain (0 = first)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameters", {
            "track_index": track_index, "device_index": device_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"


@mcp.tool()
def set_device_parameter(ctx: Context, track_index: int, device_index: int,
                         parameter: Union[int, str], value: float) -> str:
    """
    Set a device parameter (e.g. a Utility's Gain, a Compressor's Threshold) by
    its index or its name. Call get_device_parameters first to see names/ranges.
    The value is clamped to the parameter's min/max.

    Parameters:
    - track_index: The track holding the device
    - device_index: The device's index in that track's chain (0 = first)
    - parameter: Parameter index (int) or exact parameter name (str)
    - value: The value to set (in the parameter's own units, e.g. dB for Gain)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter": parameter,
            "value": value,
        })
        return (f"Set '{result.get('parameter')}' to {result.get('value')} "
                f"(range {result.get('min')}..{result.get('max')})")
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"


@mcp.tool()
def get_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Read the actual MIDI notes of a clip (pitch, start_time, duration, velocity, mute)
    so you can see its real chords/melody. MIDI clips only.

    Parameters:
    - track_index: The track holding the clip
    - clip_index: The clip slot index (Session scene - 1)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_notes", {
            "track_index": track_index, "clip_index": clip_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip notes: {str(e)}")
        return f"Error getting clip notes: {str(e)}"


@mcp.tool()
def update_notes(ctx: Context, track_index: int, clip_index: int,
                 updates: List[Dict[str, Union[int, float, bool]]]) -> str:
    """
    Surgically modify EXISTING notes in a MIDI clip without clearing/rewriting it.
    Each update matches notes by pitch + start_time (within tolerance) and applies
    the new_* fields. Much safer than clear_clip_notes + add_notes_to_clip.

    Parameters:
    - track_index: The track holding the clip
    - clip_index: The clip slot index
    - updates: List of dicts, each with:
        pitch (int, required), start_time (float, required, beats),
        tolerance (float, optional, default 0.05 beats),
        new_velocity / new_duration / new_start_time / new_pitch / new_mute (optional)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("update_notes", {
            "track_index": track_index, "clip_index": clip_index,
            "updates": updates})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error updating notes: {str(e)}")
        return f"Error updating notes: {str(e)}"


@mcp.tool()
def remove_notes_in_range(ctx: Context, track_index: int, clip_index: int,
                          from_pitch: int = 0, pitch_span: int = 128,
                          from_time: float = 0.0, time_span: float = -1.0) -> str:
    """
    Surgically remove notes inside a pitch/time window of a MIDI clip,
    keeping everything else (unlike clear_clip_notes which wipes all).

    Parameters:
    - track_index / clip_index: which clip
    - from_pitch: lowest MIDI pitch to remove (default 0)
    - pitch_span: how many pitches up from from_pitch (default 128 = all)
    - from_time: window start in beats (default 0.0)
    - time_span: window length in beats (-1 = to end of clip)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("remove_notes_in_range", {
            "track_index": track_index, "clip_index": clip_index,
            "from_pitch": from_pitch, "pitch_span": pitch_span,
            "from_time": from_time, "time_span": time_span})
        return json.dumps(result)
    except Exception as e:
        logger.error(f"Error removing notes in range: {str(e)}")
        return f"Error removing notes in range: {str(e)}"


@mcp.tool()
def set_clip_loop(ctx: Context, track_index: int, clip_index: int,
                  looping: Optional[bool] = None,
                  loop_start: Optional[float] = None,
                  loop_end: Optional[float] = None,
                  start_marker: Optional[float] = None,
                  end_marker: Optional[float] = None) -> str:
    """
    Set a clip's loop and start/end marker properties (in beats).
    Only the parameters you pass are changed.

    Parameters:
    - track_index / clip_index: which clip
    - looping: enable/disable looping
    - loop_start / loop_end: loop brace positions in beats
    - start_marker / end_marker: clip play start/end in beats
    """
    try:
        properties = {}
        if looping is not None:
            properties["looping"] = looping
        if loop_start is not None:
            properties["loop_start"] = loop_start
        if loop_end is not None:
            properties["loop_end"] = loop_end
        if start_marker is not None:
            properties["start_marker"] = start_marker
        if end_marker is not None:
            properties["end_marker"] = end_marker
        if not properties:
            return "Nothing to set: pass at least one property"
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_loop", {
            "track_index": track_index, "clip_index": clip_index,
            "properties": properties})
        return json.dumps(result)
    except Exception as e:
        logger.error(f"Error setting clip loop: {str(e)}")
        return f"Error setting clip loop: {str(e)}"


@mcp.tool()
def quantize_clip(ctx: Context, track_index: int, clip_index: int,
                  grid: int = 5, amount: float = 1.0) -> str:
    """
    Quantize a MIDI clip's notes to a grid.

    Parameters:
    - track_index / clip_index: which clip
    - grid: 1=1/4, 2=1/8, 3=1/8T, 4=1/8+T, 5=1/16 (default), 6=1/16T, 7=1/16+T, 8=1/32
    - amount: 0.0-1.0 strength (1.0 = hard snap; 0.5 keeps half the human feel)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("quantize_clip", {
            "track_index": track_index, "clip_index": clip_index,
            "grid": grid, "amount": amount})
        return json.dumps(result)
    except Exception as e:
        logger.error(f"Error quantizing clip: {str(e)}")
        return f"Error quantizing clip: {str(e)}"


@mcp.tool()
def get_drum_pad_names(ctx: Context, track_index: int) -> str:
    """
    List which MIDI note triggers which drum pad/instrument on the first
    Drum Rack of a track (e.g. 36=Kick 808, 38=Snare...). Call this before
    writing/fixing drum MIDI so you know what each pitch plays.

    Parameters:
    - track_index: The track holding the Drum Rack
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_drum_pad_names", {
            "track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting drum pad names: {str(e)}")
        return f"Error getting drum pad names: {str(e)}"


@mcp.tool()
def bounce_midi_clip_to_audio(ctx: Context, track_index: int, clip_index: int,
                              extra_tail_beats: float = 4.0,
                              dest_track_index: int = -1) -> str:
    """
    Bounce (record) a MIDI clip's audible output to an audio clip, in REAL TIME
    via resampling-record (Live's Freeze/Flatten is not automatable). Creates an
    audio track (or uses dest_track_index), routes the MIDI track's Post FX
    output into it, records the clip in the same scene row, and auto-stops after
    clip length + tail. Returns immediately — wait the reported duration_seconds,
    then verify with get_track_info / get_arrangement_clips.

    Playback is audible during the bounce; don't change the session while recording.

    Parameters:
    - track_index: source MIDI track
    - clip_index: source clip slot (recording lands in the SAME slot row on the audio track)
    - extra_tail_beats: extra beats recorded for reverb/delay tails (default 4)
    - dest_track_index: existing audio track to record into (-1 = create new '[BOUNCE]' track)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("bounce_midi_clip_to_audio", {
            "track_index": track_index, "clip_index": clip_index,
            "extra_tail_beats": extra_tail_beats,
            "dest_track_index": dest_track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error bouncing MIDI clip to audio: {str(e)}")
        return f"Error bouncing MIDI clip to audio: {str(e)}"


@mcp.tool()
def get_scene_names(ctx: Context) -> str:
    """
    List all Session scenes: index, name, tempo hint (if the scene name sets one)
    and whether the scene is empty. Use before firing/organizing scenes.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_scene_names", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scene names: {str(e)}")
        return f"Error getting scene names: {str(e)}"


@mcp.tool()
def undo(ctx: Context) -> str:
    """
    Undo the last action in Ableton Live (equivalent to Cmd+Z).
    Returns can_undo and can_redo flags after the operation so the caller
    knows whether further undo/redo steps are available.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("undo", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error performing undo: {str(e)}")
        return f"Error performing undo: {str(e)}"


@mcp.tool()
def redo(ctx: Context) -> str:
    """
    Redo the last undone action in Ableton Live (equivalent to Cmd+Shift+Z).
    Returns can_undo and can_redo flags after the operation.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("redo", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error performing redo: {str(e)}")
        return f"Error performing redo: {str(e)}"


@mcp.tool()
def set_track_pan(ctx: Context, track_index: int, pan: float) -> str:
    """
    Set a track's stereo panning position.

    Parameters:
    - track_index: The index of the track
    - pan: Pan value -1.0 (full left) to 1.0 (full right); 0.0 = center
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_pan",
                                      {"track_index": track_index, "pan": pan})
        return f"Set track {track_index} pan to {result.get('pan')}"
    except Exception as e:
        logger.error(f"Error setting track pan: {str(e)}")
        return f"Error setting track pan: {str(e)}"


@mcp.tool()
def set_track_mute(ctx: Context, track_index: int, mute: bool) -> str:
    """
    Mute or unmute a track.

    Parameters:
    - track_index: The index of the track
    - mute: True to mute, False to unmute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_mute",
                                      {"track_index": track_index, "mute": mute})
        return f"Set track {track_index} mute to {result.get('mute')}"
    except Exception as e:
        logger.error(f"Error setting track mute: {str(e)}")
        return f"Error setting track mute: {str(e)}"


@mcp.tool()
def set_track_solo(ctx: Context, track_index: int, solo: bool) -> str:
    """
    Solo or unsolo a track.

    Parameters:
    - track_index: The index of the track
    - solo: True to solo, False to unsolo
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_solo",
                                      {"track_index": track_index, "solo": solo})
        return f"Set track {track_index} solo to {result.get('solo')}"
    except Exception as e:
        logger.error(f"Error setting track solo: {str(e)}")
        return f"Error setting track solo: {str(e)}"


@mcp.tool()
def get_return_tracks(ctx: Context) -> str:
    """
    List all return tracks (A, B, C…) with their names and loaded devices.
    Use before set_send_level to know available return track indices.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_return_tracks", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting return tracks: {str(e)}")
        return f"Error getting return tracks: {str(e)}"


@mcp.tool()
def set_send_level(ctx: Context, track_index: int, send_index: int, level: float) -> str:
    """
    Set a track's send level to a return track.

    Parameters:
    - track_index: The index of the source track
    - send_index: The index of the send (0 = first return track / Send A)
    - level: Normalized level 0.0-1.0 (0.0 = off, 0.85 ~ 0 dB, 1.0 = max)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_send_level", {
            "track_index": track_index,
            "send_index": send_index,
            "level": level,
        })
        return f"Set track {track_index} send {send_index} to {result.get('level')}"
    except Exception as e:
        logger.error(f"Error setting send level: {str(e)}")
        return f"Error setting send level: {str(e)}"


@mcp.tool()
def get_meters(ctx: Context) -> str:
    """
    Snapshot the current output meter levels for every track and the master.
    Returns output_meter_left and output_meter_right (0.0-1.0 linear peak)
    for each track, plus output_meter_level where available. Call repeatedly
    during playback to poll levels; each call is a single instantaneous sample.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_meters", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting meters: {str(e)}")
        return f"Error getting meters: {str(e)}"


# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()
