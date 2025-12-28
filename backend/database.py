import os
import logging
from azure.cosmos import CosmosClient, exceptions
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("docgen.db")

# --- Cosmos DB Configuration ---
COSMOS_URI = os.getenv("COSMOS_DB_URI")
COSMOS_KEY = os.getenv("COSMOS_DB_KEY")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME", "docorator_db")

users_container = None
documents_container = None

def init_cosmos():
    global users_container, documents_container
    if not COSMOS_URI or not COSMOS_KEY:
        logger.warning("COSMOS_DB_URI or COSMOS_DB_KEY not set. Database features will be disabled.")
        return

    try:
        client = CosmosClient(COSMOS_URI, credential=COSMOS_KEY)
        db = client.create_database_if_not_exists(id=COSMOS_DB_NAME)
        
        users_container = db.create_container_if_not_exists(
            id="users", 
            partition_key="/email",
            offer_throughput=400 
        )
        documents_container = db.create_container_if_not_exists(
            id="documents",
            partition_key="/user_id",
            offer_throughput=400
        )
        logger.info(f"Connected to Cosmos DB: {COSMOS_DB_NAME}")
    except Exception as e:
        logger.error(f"Failed to initialize Cosmos DB: {str(e)}")
        # Don't crash app on startup, just log error. 
        # API endpoints will fail if they try to use it.

# Initialize on import (or can be called by startup event)
init_cosmos()

def get_db():
    """Dependency for FastAPI routes"""
    # For Cosmos, we just return the containers or a wrapper
    # Since we are using global clients, we can just return a dict or similar
    if users_container is None:
        # Try to init again if failed previously? Or just error
        # Re-try init
        init_cosmos()
        if users_container is None:
             raise Exception("Database not initialized")
    
    return {
        "users": users_container,
        "documents": documents_container
    }
