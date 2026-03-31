import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

@dataclass
class JsonRpcRequest:
    jsonrpc: str
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Any] = None

@dataclass
class JsonRpcResponse:
    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[Any] = None

    def to_dict(self):
        d = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return d

class MCPSession:
    """
    Manages an MCP session. Simple in-memory storage for now?
    Django architecture is stateless usually.
    We need to persist messages destined for the client if checking/polling?
    SSE pushes responses.
    Client sends POST requests.
    If the POST request (CallTool) takes time, can we respond synchronously in the POST response?
    No, Protocol says POST should return 202 Accepted and response sent via SSE?
    Or 200 OK?
    
    Standard MCP over SSE:
    1. Client -> SSE GET. Connection open.
    2. Server -> Sends 'endpoint' event: `POST /mcp/messages`.
    3. Client -> POST `call_tool`.
    4. Server -> Processes. Sends `jsonrpc` response event via SSE.
       POST returns 202 Accepted.
    
    So we need shared state (Session ID -> SSE Channel).
    But Django runserver/gunicorn implies multiple workers.
    Standard Django Channels is needed for SSE/WebSockets cross-process communication.
    
    However, if we are running standard sync Django with Gunicorn, SSE keeps a persistent connection on ONE worker.
    But the POST request arrives at potentially ANOTHER worker.
    The Worker A (SSE) needs to send data.
    Worker B (POST) processes data and needs to tell Worker A to send.
    
    Without Redis/Channels, we cannot communicate between workers.
    
    CRITICAL: Without Django Channels, we CANNOT implement true SSE where POST triggers SSE emit on another process.
    BUT, if we use a single thread/process for dev, it works. For production (K8s deployment), it breaks.
    
    Pivot: Does MCP support HTTP Transport (Stateless)?
    Official MCP Spec supports:
    - Stdio
    - SSE
    
    If we can't efficiently do SSE in Django without Channels, maybe we should use Long Polling or just handle it if we can.
    
    Users existing app is standard Django. Adding "channels" (Daphne/Redis) is a big infra change.
    
    Workaround:
    "StreamingHttpResponse" keeps the connection open.
    If we can't assume shared memory/IPC...
    
    Maybe we can assume the POST request *is* the response?
    But protocol separates them.
    
    Wait, could we just return the result in the POST response?
    Some MCP clients might accept that?
    Protocol says: "The server MUST respond to the POST request with 202 Accepted... responses are sent via the SSE connection".
    
    So we need IPC.
    Using Database as IPC?
    Worker A (SSE) loops:
      while connection_open:
         messages = MsgQueue.pop(session_id)
         yield messages
         sleep(0.1)
         
    This is "Long Polling" implemented over SSE stream. It works with standard Django/Postgres.
    
    We will implement this "Db-backed SSE Queue".
    """
    pass
