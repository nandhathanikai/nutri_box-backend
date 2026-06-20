import os
import logging
import cloudinary
import cloudinary.uploader
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Fetch environment credentials
CLOUD_NAME = os.getenv("CLOUD_NAME")
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY")
CLOUD_API_SECRET = os.getenv("CLOUD_API_SECRET")

# Flag to verify configuration status
is_cloudinary_configured = False

if CLOUD_NAME and CLOUD_API_KEY and CLOUD_API_SECRET:
    try:
        cloudinary.config(
            cloud_name=CLOUD_NAME,
            api_key=CLOUD_API_KEY,
            api_secret=CLOUD_API_SECRET,
            secure=True
        )
        is_cloudinary_configured = True
        logger.info("Cloudinary successfully configured.")
    except Exception as e:
        logger.error(f"Error configuring Cloudinary: {e}")
else:
    logger.warning("Cloudinary credentials missing from environment. Cloudinary uploads will not be available.")


def get_resource_type(content_type: str, filename: str) -> str:
    """
    Detect the Cloudinary resource type ('image', 'video', or 'raw') 
    based on the file content type or extension.
    """
    content_type_lower = (content_type or "").lower().strip()
    ext = (filename or "").lower().split(".")[-1] if filename and "." in filename else ""

    if content_type_lower.startswith("image/") or ext in {"jpg", "jpeg", "png", "webp", "gif", "svg", "bmp"}:
        return "image"
    elif content_type_lower.startswith("video/") or ext in {"mp4", "webm", "mov", "avi", "mkv", "ogg", "flv"}:
        return "video"
    elif content_type_lower == "application/pdf" or ext == "pdf":
        return "raw"
    return "auto"


def upload_file_to_cloudinary(file_content: bytes, filename: str, content_type: str, folder: str = "nutribox") -> str:
    """
    Upload file bytes to Cloudinary and return the secure HTTPS URL.
    """
    if not is_cloudinary_configured:
        raise HTTPException(
            status_code=503,
            detail={
                "error_type": "cloudinary_not_configured",
                "message": "Cloudinary storage is not configured on the server. Please check your credentials in .env.",
                "raw": "is_cloudinary_configured = False"
            }
        )

    if not file_content:
        raise HTTPException(
            status_code=400,
            detail={
                "error_type": "empty_file",
                "message": "The uploaded file is empty. Please select a valid file.",
                "raw": "file_content length is 0"
            }
        )

    resource_type = get_resource_type(content_type, filename)

    try:
        # Upload to Cloudinary using file bytes
        response = cloudinary.uploader.upload(
            file_content,
            folder=folder,
            resource_type=resource_type,
            unique_filename=True
        )
        
        secure_url = response.get("secure_url")
        if not secure_url:
            raise ValueError("Cloudinary response did not include secure_url")
            
        logger.info(f"Successfully uploaded {filename} to Cloudinary. URL: {secure_url}")
        return secure_url

    except Exception as exc:
        logger.error(f"Cloudinary upload exception for {filename}: {exc}")
        
        # Raise standard HTTPException that mimics original Supabase error format
        raise HTTPException(
            status_code=502,
            detail={
                "error_type": "cloudinary_upload_failed",
                "message": f"Failed to upload file to Cloudinary: {str(exc)}",
                "raw": str(exc)
            }
        )
